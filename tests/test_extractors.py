from __future__ import annotations

import io
import tarfile

import pytest
import requests

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


def _response(mocker, status=200, content=b"", exc=None):
    if exc is not None:
        mock = mocker.Mock()
        mock.get.side_effect = exc
        return mock
    resp = mocker.Mock()
    resp.status_code = status
    resp.content = content
    resp.raise_for_status = mocker.Mock()
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status}")
    session = mocker.Mock()
    session.get.return_value = resp
    return session


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    mocker.patch("sci_etl_core.extractors.arxiv.time.sleep")


def _build(session, mocker, **kwargs):
    return ArxivExtractor(
        user_agent="test-agent/1.0",
        pdf_parser=mocker.Mock(spec=PdfPlumberParser),
        latex_parser=mocker.Mock(spec=LatexTarballParser),
        session=session,
        **kwargs,
    )


class TestArxivSearch:
    def test_returns_content_on_success(self, mocker):
        session = _response(mocker, status=200, content=b"<feed/>")
        extractor = _build(session, mocker)
        assert extractor.search("q", 10, 0) == b"<feed/>"

    def test_retries_then_succeeds_after_transient_error(self, mocker):
        resp_ok = mocker.Mock(status_code=200, content=b"ok")
        resp_ok.raise_for_status = mocker.Mock()
        session = mocker.Mock()
        session.get.side_effect = [requests.exceptions.ConnectionError("boom"), resp_ok]
        extractor = _build(session, mocker, max_retries=3)
        assert extractor.search("q", 10, 0) == b"ok"
        assert session.get.call_count == 2

    def test_handles_429_by_retrying(self, mocker):
        resp_429 = mocker.Mock(status_code=429, content=b"")
        resp_429.raise_for_status = mocker.Mock()
        resp_ok = mocker.Mock(status_code=200, content=b"ok")
        resp_ok.raise_for_status = mocker.Mock()
        session = mocker.Mock()
        session.get.side_effect = [resp_429, resp_ok]
        extractor = _build(session, mocker, max_retries=3)
        assert extractor.search("q", 10, 0) == b"ok"
        assert session.get.call_count == 2

    def test_returns_none_after_exhausting_retries(self, mocker):
        session = mocker.Mock()
        session.get.side_effect = requests.exceptions.Timeout("timeout")
        logged = []
        extractor = _build(session, mocker, max_retries=3, logger=logged.append)
        assert extractor.search("q", 10, 0) is None
        assert session.get.call_count == 3
        assert any("failed" in msg.lower() for msg in logged)

    def test_raises_nothing_on_500_but_returns_none(self, mocker):
        session = _response(mocker, status=500)
        extractor = _build(session, mocker, max_retries=2)
        assert extractor.search("q", 10, 0) is None


class TestArxivParseListing:
    def test_parses_all_new_entries(self, mocker):
        extractor = _build(mocker.Mock(), mocker)
        records, total = extractor.parse_listing(ATOM_TEMPLATE.encode(), seen_ids=set())
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00001v1", "2401.00002v1"]
        assert records[0].source_url and "html" in records[0].source_url

    def test_skips_already_seen_ids(self, mocker):
        extractor = _build(mocker.Mock(), mocker)
        records, total = extractor.parse_listing(ATOM_TEMPLATE.encode(), seen_ids={"2401.00001v1"})
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00002v1"]

    def test_empty_feed_returns_no_records(self, mocker):
        extractor = _build(mocker.Mock(), mocker)
        records, total = extractor.parse_listing(b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>", set())
        assert records == []
        assert total == 0


class TestArxivFetchFullText:
    def _tarball(self, body: bytes) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(mode="w:gz", fileobj=buf) as tar:
            info = tarfile.TarInfo("main.tex")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
        return buf.getvalue()

    def test_prefers_latex_source(self, mocker):
        session = mocker.Mock()
        session.get.return_value = mocker.Mock(status_code=200, content=b"raw-latex")
        latex_parser = mocker.Mock(spec=LatexTarballParser)
        latex_parser.extract_text.return_value = "Full LaTeX body without references."
        extractor = ArxivExtractor(
            user_agent="ua", pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=latex_parser, session=session,
        )
        record = RawRecord(record_id="2401.1", title="t", abstract="fallback")
        assert "LaTeX body" in extractor.fetch_full_text(record)

    def test_falls_back_to_pdf_when_latex_empty(self, mocker):
        session = mocker.Mock()
        session.get.return_value = mocker.Mock(status_code=200, content=b"bytes")
        latex_parser = mocker.Mock(spec=LatexTarballParser)
        latex_parser.extract_text.return_value = ""
        pdf_parser = mocker.Mock(spec=PdfPlumberParser)
        pdf_parser.extract_text.return_value = "PDF extracted text."
        extractor = ArxivExtractor(
            user_agent="ua", pdf_parser=pdf_parser, latex_parser=latex_parser, session=session
        )
        record = RawRecord(record_id="2401.2", title="t", abstract="fallback")
        assert "PDF extracted" in extractor.fetch_full_text(record)

    def test_falls_back_to_abstract_when_all_fetches_fail(self, mocker):
        session = mocker.Mock()
        session.get.return_value = mocker.Mock(status_code=404, content=b"")
        extractor = _build(session, mocker)
        record = RawRecord(record_id="2401.3", title="t", abstract="the abstract")
        assert extractor.fetch_full_text(record) == "the abstract"

    def test_empty_record_id_returns_abstract_immediately(self, mocker):
        session = mocker.Mock()
        extractor = _build(session, mocker)
        record = RawRecord(record_id="", title="t", abstract="just the abstract")
        assert extractor.fetch_full_text(record) == "just the abstract"
        session.get.assert_not_called()

    def test_network_exception_during_fetch_is_swallowed(self, mocker):
        session = mocker.Mock()
        session.get.side_effect = requests.exceptions.ConnectionError("down")
        logged = []
        extractor = _build(session, mocker, logger=logged.append)
        record = RawRecord(record_id="2401.4", title="t", abstract="safe fallback")
        assert extractor.fetch_full_text(record) == "safe fallback"
