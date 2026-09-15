from __future__ import annotations

import httpx
import pytest

from sci_etl_core.exceptions import MalformedResponseError, UpstreamError
from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser

ATOM = """<?xml version="1.0"?>
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


def _resp(mocker, status=200, content=b""):
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
    return AsyncArxivExtractor(
        client=client,
        pdf_parser=mocker.Mock(spec=PdfPlumberParser),
        latex_parser=mocker.Mock(spec=LatexTarballParser),
        sleep=mocker.AsyncMock(),
        **kwargs,
    )


class TestAsyncArxivSearch:
    @pytest.mark.asyncio
    async def test_returns_content_on_success(self, mocker):
        extractor = _build(_client(mocker, resp=_resp(mocker, 200, b"<feed/>")), mocker)
        assert await extractor.search("q", 10, 0) == b"<feed/>"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds_after_transient_error(self, mocker):
        client = _client(mocker, side_effect=[httpx.ConnectError("boom"), _resp(mocker, 200, b"ok")])
        extractor = _build(client, mocker, max_retries=3)
        assert await extractor.search("q", 10, 0) == b"ok"
        assert client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_handles_429_by_retrying(self, mocker):
        client = _client(mocker, side_effect=[_resp(mocker, 429), _resp(mocker, 200, b"ok")])
        extractor = _build(client, mocker, max_retries=3)
        assert await extractor.search("q", 10, 0) == b"ok"
        assert client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_raises_upstream_error_after_exhausting_retries(self, mocker):
        logged: list[str] = []
        client = _client(mocker, side_effect=httpx.TimeoutException("timeout"))
        extractor = _build(client, mocker, max_retries=3, logger=logged.append)
        with pytest.raises(UpstreamError, match="after 3 attempts") as excinfo:
            await extractor.search("q", 10, 0)
        assert isinstance(excinfo.value.__cause__, httpx.TimeoutException)
        assert client.get.await_count == 3
        assert any("failed" in msg.lower() for msg in logged)

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_500(self, mocker):
        extractor = _build(_client(mocker, resp=_resp(mocker, 500)), mocker, max_retries=2)
        with pytest.raises(UpstreamError):
            await extractor.search("q", 10, 0)

    @pytest.mark.parametrize("max_retries", [0, -1])
    def test_max_retries_below_one_is_rejected(self, mocker, max_retries):
        with pytest.raises(ValueError, match="max_retries"):
            _build(_client(mocker), mocker, max_retries=max_retries)


class TestAsyncArxivParseListing:
    def test_parses_all_new_entries(self, mocker):
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(ATOM.encode(), seen_ids=set())
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00001v1", "2401.00002v1"]
        assert records[0].source_url and "html" in records[0].source_url

    def test_skips_already_seen_ids(self, mocker):
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(ATOM.encode(), seen_ids={"2401.00001v1"})
        assert total == 2
        assert [r.record_id for r in records] == ["2401.00002v1"]

    def test_skips_duplicate_base_ids_within_same_feed(self, mocker):
            """Two entries with the same base id but different versions — only the first is kept."""
            feed = (
                "<?xml version='1.0'?>"
                "<feed xmlns='http://www.w3.org/2005/Atom'>"
                "<entry><id>http://arxiv.org/abs/2401.00001v1</id>"
                "<title>First</title><summary>Abstract 1</summary></entry>"
                "<entry><id>http://arxiv.org/abs/2401.00001v2</id>"
                "<title>Second</title><summary>Abstract 2</summary></entry>"
                "</feed>"
            )
            extractor = _build(_client(mocker), mocker)
            records, total = extractor.parse_listing(feed.encode(), seen_ids=set())
            assert total == 2
            assert len(records) == 1
            assert records[0].record_id == "2401.00001v1"

    def test_empty_feed_returns_no_records(self, mocker):
        extractor = _build(_client(mocker), mocker)
        records, total = extractor.parse_listing(b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>", set())
        assert records == []
        assert total == 0

    @pytest.mark.parametrize("payload", [b"", b"   ", b"<<<not xml at all>>>", b"<other/>"])
    def test_malformed_payload_raises_instead_of_reporting_end(self, mocker, payload):
        extractor = _build(_client(mocker), mocker)
        with pytest.raises(MalformedResponseError):
            extractor.parse_listing(payload, set())


def _single_entry_feed(entry_body: str) -> bytes:
    return (
        "<?xml version='1.0'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>"
        "<entry><id>http://arxiv.org/abs/2401.00001v1</id><title>T</title><summary>S</summary>"
        f"{entry_body}</entry></feed>"
    ).encode()


class TestAsyncArxivListingMetadata:
    def test_holds_categories_authors_published_and_year(self, mocker):
        feed = _single_entry_feed(
            "<published>2024-01-02T18:00:00Z</published>"
            "<author><name>Ada Lovelace</name><arxiv:affiliation>Analytical Engines</arxiv:affiliation></author>"
            "<author><name>Carl Sagan</name></author>"
            "<arxiv:primary_category term='astro-ph.GA' scheme='http://arxiv.org/schemas/atom'/>"
            "<category term='astro-ph.GA' scheme='http://arxiv.org/schemas/atom'/>"
            "<category term='astro-ph.CO' scheme='http://arxiv.org/schemas/atom'/>"
        )
        (record,), _ = _build(_client(mocker), mocker).parse_listing(feed, set())
        assert record.metadata == {
            "categories": ["astro-ph.GA", "astro-ph.CO"],
            "authors": ["Ada Lovelace", "Carl Sagan"],
            "published": "2024-01-02T18:00:00Z",
            "year": "2024",
        }

    def test_an_entry_without_categories_or_authors_gets_empty_lists(self, mocker):
        (record,), _ = _build(_client(mocker), mocker).parse_listing(_single_entry_feed(""), set())
        assert record.metadata == {"categories": [], "authors": []}

    @pytest.mark.parametrize("published", ["", "<published>   </published>"])
    def test_a_missing_or_blank_published_date_omits_published_and_year(self, mocker, published):
        (record,), _ = _build(_client(mocker), mocker).parse_listing(_single_entry_feed(published), set())
        assert "published" not in record.metadata
        assert "year" not in record.metadata

    @pytest.mark.parametrize("published", ["January 2024", "24-01-02", "20245-01-02", "２０２４-01-02", "2024"])
    def test_year_is_taken_only_from_a_leading_four_digit_year(self, mocker, published):
        feed = _single_entry_feed(f"<published>{published}</published>")
        (record,), _ = _build(_client(mocker), mocker).parse_listing(feed, set())
        assert record.metadata["published"] == published
        assert record.metadata.get("year") == ("2024" if published == "2024" else None)

    def test_a_repeated_category_is_kept_as_sent(self, mocker):
        feed = _single_entry_feed("<category term='astro-ph.GA'/><category term='astro-ph.GA'/>")
        (record,), _ = _build(_client(mocker), mocker).parse_listing(feed, set())
        assert record.metadata["categories"] == ["astro-ph.GA", "astro-ph.GA"]

    def test_blank_or_missing_terms_and_names_are_skipped(self, mocker):
        feed = _single_entry_feed(
            "<category term='  '/><category/><category term=' hep-th '/>"
            "<author><name> </name></author><author/><author><name>Vera Rubin</name></author>"
        )
        (record,), _ = _build(_client(mocker), mocker).parse_listing(feed, set())
        assert record.metadata == {"categories": ["hep-th"], "authors": ["Vera Rubin"]}


class TestAsyncArxivFetchFullText:
    @pytest.mark.asyncio
    async def test_prefers_latex_source(self, mocker):
        latex = mocker.Mock(spec=LatexTarballParser)
        latex.extract_text.return_value = "Full LaTeX body without references."
        extractor = AsyncArxivExtractor(
            client=_client(mocker, resp=_resp(mocker, 200, b"raw-latex")),
            pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=latex,
            sleep=mocker.AsyncMock(),
        )
        record = RawRecord(record_id="2401.1", title="t", abstract="fallback")
        assert "LaTeX body" in await extractor.fetch_full_text(record)

    @pytest.mark.asyncio
    async def test_falls_back_to_pdf_when_latex_empty(self, mocker):
        latex = mocker.Mock(spec=LatexTarballParser)
        latex.extract_text.return_value = ""
        pdf = mocker.Mock(spec=PdfPlumberParser)
        pdf.extract_text.return_value = "PDF extracted text."
        extractor = AsyncArxivExtractor(
            client=_client(mocker, resp=_resp(mocker, 200, b"bytes")),
            pdf_parser=pdf,
            latex_parser=latex,
            sleep=mocker.AsyncMock(),
        )
        record = RawRecord(record_id="2401.2", title="t", abstract="fallback")
        assert "PDF extracted" in await extractor.fetch_full_text(record)

    @pytest.mark.asyncio
    async def test_falls_back_to_abstract_when_all_fetches_fail(self, mocker):
        extractor = _build(_client(mocker, resp=_resp(mocker, 404)), mocker)
        record = RawRecord(record_id="2401.3", title="t", abstract="the abstract")
        assert await extractor.fetch_full_text(record) == "the abstract"

    @pytest.mark.asyncio
    async def test_empty_record_id_returns_abstract_immediately(self, mocker):
        client = _client(mocker)
        extractor = _build(client, mocker)
        record = RawRecord(record_id="", title="t", abstract="just the abstract")
        assert await extractor.fetch_full_text(record) == "just the abstract"
        assert client.get.await_count == 0

    @pytest.mark.asyncio
    async def test_network_failure_raises_instead_of_falling_back(self, mocker):
        logged: list[str] = []
        client = _client(mocker, side_effect=httpx.ConnectError("down"))
        extractor = _build(client, mocker, logger=logged.append)
        record = RawRecord(record_id="2401.4", title="t", abstract="safe fallback")
        with pytest.raises(UpstreamError, match="2401.4"):
            await extractor.fetch_full_text(record)
        assert any("failed" in message for message in logged)


class TestAsyncArxivNormalizeId:
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

class TestAsyncArxivInternals:
    @pytest.mark.asyncio
    async def test_fetch_latex_source_returns_none_on_404(self, mocker):
        extractor = _build(_client(mocker, resp=_resp(mocker, 404)), mocker)
        assert await extractor._fetch_latex_source("2401.1") is None

    @pytest.mark.asyncio
    async def test_get_bytes_raises_after_exhausting_network_retries(self, mocker):
        client = _client(mocker, side_effect=httpx.ConnectError("down"))
        extractor = _build(client, mocker)
        with pytest.raises(UpstreamError, match="after 3 attempts"):
            await extractor._get_bytes("http://x", "X", "id")
        assert client.get.await_count == 3

    @pytest.mark.asyncio
    async def test_get_bytes_returns_none_on_fatal_status(self, mocker):
        client = _client(mocker, resp=_resp(mocker, 404))
        extractor = _build(client, mocker)
        assert await extractor._get_bytes("http://x", "X", "id") is None
        assert client.get.await_count == 1

    @pytest.mark.asyncio
    async def test_get_bytes_retries_retryable_status_then_succeeds(self, mocker):
        client = _client(mocker, side_effect=[_resp(mocker, 503), _resp(mocker, 200, b"payload")])
        extractor = _build(client, mocker)
        assert await extractor._get_bytes("http://x", "X", "id") == b"payload"
        assert client.get.await_count == 2

