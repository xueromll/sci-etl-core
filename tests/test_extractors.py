from __future__ import annotations

import httpx
import pytest

from sci_etl_core.extractors.arxiv import ArxivExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser

ATOM_TEMPLATE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>First Paper</title>
    <summary>First abstract.</summary>
    <link href="http://arxiv.org/abs/2401.00001v1"/>
    <link href="http://arxiv.org/html/2401.00001v1" rel="alternate" type="text/html"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Second Paper</title>
    <summary>Second abstract.</summary>
  </entry>
</feed>"""


def _response(mocker, status=200, content=b""):
    resp = mocker.Mock()
    resp.status_code = status
    resp.content = content
    resp.raise_for_status = mocker.Mock()
    return resp


def _client(mocker, *, resp=None, side_effect=None):
    client = mocker.Mock()
    client.get = mocker.AsyncMock(return_value=resp, side_effect=side_effect)
    return client


def _build(client, mocker, **kwargs):
    return ArxivExtractor(
        client=client,
        pdf_parser=mocker.Mock(spec=PdfPlumberParser),
        latex_parser=mocker.Mock(spec=LatexTarballParser),
        sleep=mocker.AsyncMock(),
        **kwargs,
    )


class TestArxivSearch:
    def test_returns_content_on_success(self, mocker):
        extractor = _build(_client(mocker, resp=_response(mocker, 200, b"<feed/>")), mocker)
        assert extractor.search("q", 10, 0) == b"<feed/>"

    def test_retries_then_succeeds_after_transient_error(self, mocker):
        client = _client(mocker, side_effect=[httpx.ConnectError("boom"), _response(mocker, 200, b"ok")])
        extractor = _build(client, mocker, max_retries=3)
        assert extractor.search("q", 10, 0) == b"ok"
        assert client.get.await_count == 2

    def test_handles_429_by_retrying(self, mocker):
        client = _client(mocker, side_effect=[_response(mocker, 429), _response(mocker, 200, b"ok")])
        extractor = _build(client, mocker, max_retries=3)
        assert extractor.search("q", 10, 0) == b"ok"
        assert client.get.await_count == 2

    def test_returns_none_after_exhausting_retries(self, mocker):
        logged: list[str] = []
        client = _client(mocker, side_effect=httpx.TimeoutException("timeout"))
        extractor = _build(client, mocker, max_retries=3, logger=logged.append)
        assert extractor.search("q", 10, 0) is None
        assert client.get.await_count == 3
        assert any("failed" in msg.lower() for msg in logged)

    def test_raises_nothing_on_500_but_returns_none(self, mocker):
        extractor = _build(_client(mocker, resp=_response(mocker, 500)), mocker, max_retries=2)
        assert extractor.search("q", 10, 0) is None


class TestArxivParseListing:
    def test_parses_all_new_entries(self, mocker):
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(ATOM_TEMPLATE.encode(), seen_ids=set())
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00001v1", "2401.00002v1"]
        assert records[0].source_url and "html" in records[0].source_url

    def test_skips_already_seen_ids(self, mocker):
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(ATOM_TEMPLATE.encode(), seen_ids={"2401.00001v1"})
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00002v1"]

    def test_empty_feed_returns_no_records(self, mocker):
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>", set())
        assert records == []
        assert total == 0


class TestArxivFetchFullText:
    def test_prefers_latex_source(self, mocker):
        latex_parser = mocker.Mock(spec=LatexTarballParser)
        latex_parser.extract_text.return_value = "Full LaTeX body without references."
        extractor = ArxivExtractor(
            client=_client(mocker, resp=_response(mocker, 200, b"raw-latex")),
            pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=latex_parser,
            sleep=mocker.AsyncMock(),
        )
        record = RawRecord(record_id="2401.1", title="t", abstract="fallback")
        assert "LaTeX body" in extractor.fetch_full_text(record)

    def test_falls_back_to_pdf_when_latex_empty(self, mocker):
        latex_parser = mocker.Mock(spec=LatexTarballParser)
        latex_parser.extract_text.return_value = ""
        pdf_parser = mocker.Mock(spec=PdfPlumberParser)
        pdf_parser.extract_text.return_value = "PDF extracted text."
        extractor = ArxivExtractor(
            client=_client(mocker, resp=_response(mocker, 200, b"bytes")),
            pdf_parser=pdf_parser,
            latex_parser=latex_parser,
            sleep=mocker.AsyncMock(),
        )
        record = RawRecord(record_id="2401.2", title="t", abstract="fallback")
        assert "PDF extracted" in extractor.fetch_full_text(record)

    def test_falls_back_to_abstract_when_all_fetches_fail(self, mocker):
        extractor = _build(_client(mocker, resp=_response(mocker, 404)), mocker)
        record = RawRecord(record_id="2401.3", title="t", abstract="the abstract")
        assert extractor.fetch_full_text(record) == "the abstract"

    def test_empty_record_id_returns_abstract_immediately(self, mocker):
        client = _client(mocker)
        extractor = _build(client, mocker)
        record = RawRecord(record_id="", title="t", abstract="just the abstract")
        assert extractor.fetch_full_text(record) == "just the abstract"
        assert client.get.await_count == 0

    def test_network_exception_during_fetch_is_swallowed(self, mocker):
        logged: list[str] = []
        client = _client(mocker, side_effect=httpx.ConnectError("down"))
        extractor = _build(client, mocker, logger=logged.append)
        record = RawRecord(record_id="2401.4", title="t", abstract="safe fallback")
        assert extractor.fetch_full_text(record) == "safe fallback"


class TestArxivNormalizeId:
    def test_strips_abs_prefix(self, mocker):
        extractor = _build(_client(mocker), mocker)
        assert extractor._normalize_id("http://arxiv.org/abs/2401.00001v1") == "2401.00001v1"

    def test_strips_pdf_prefix_and_suffix(self, mocker):
        extractor = _build(_client(mocker), mocker)
        assert extractor._normalize_id("http://arxiv.org/pdf/2401.00002.pdf") == "2401.00002"

    def test_returns_bare_id_unchanged(self, mocker):
        extractor = _build(_client(mocker), mocker)
        assert extractor._normalize_id("2401.00003") == "2401.00003"

    def test_pdf_ids_flow_through_parse_listing(self, mocker):
        feed = (
            "<?xml version='1.0'?>"
            "<feed xmlns='http://www.w3.org/2005/Atom'>"
            "<entry><id>http://arxiv.org/pdf/2401.00009.pdf</id>"
            "<title>P</title><summary>s</summary></entry>"
            "<entry><id>2401.00010</id><title>Q</title><summary>s</summary></entry>"
            "</feed>"
        )
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(feed.encode(), seen_ids=set())
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00009", "2401.00010"]


class TestArxivParseListingDeduplication:
    def test_skips_duplicate_base_id_within_same_listing(self, mocker):
        feed = (
            "<?xml version='1.0'?>"
            "<feed xmlns='http://www.w3.org/2005/Atom'>"
            "<entry><id>http://arxiv.org/abs/2401.00050v2</id>"
            "<title>Newer</title><summary>s</summary></entry>"
            "<entry><id>http://arxiv.org/abs/2401.00050v1</id>"
            "<title>Older</title><summary>s</summary></entry>"
            "</feed>"
        )
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(feed.encode(), seen_ids=set())
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00050v2"]
