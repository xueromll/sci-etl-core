from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from sci_etl_core.exceptions import ExtractionError, MalformedResponseError, ParsingError, UpstreamError
from sci_etl_core.extractors import AsyncOpenAlexExtractor, AsyncPubMedExtractor, AsyncSemanticScholarExtractor
from sci_etl_core.extractors._http import RetryingFetcher
from sci_etl_core.extractors.openalex_async import reconstruct_abstract
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.rate_limiter import AsyncRateLimiter

JATS = (Path(__file__).parents[1] / "data" / "jats_article.xml").read_bytes()


class Router:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handlers: list = []

    def add(self, predicate, *responses) -> None:
        self.handlers.append((predicate, list(responses)))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for predicate, responses in self.handlers:
            if predicate(request):
                response = responses.pop(0) if len(responses) > 1 else responses[0]
                if isinstance(response, Exception):
                    raise response
                return response
        return httpx.Response(404)


def _client(router: Router) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(router))


class StubPdfParser(Parser):
    def __init__(self, text: str = "PDF body.\n\nReferences\n[1] cited", error: bool = False) -> None:
        self._text = text
        self._error = error

    def extract_text(self, content: bytes) -> str:
        if self._error:
            raise ParsingError("not a pdf")
        return self._text


async def _no_sleep(_delay):
    return None


class CountingLimiter(AsyncRateLimiter):
    def __init__(self) -> None:
        self.entered = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *exc):
        return None


class TestRetryingFetcher:
    def _fetcher(self, router, lines, **kwargs):
        options = dict(max_retries=3, backoff_factor=2.0, max_retry_after=5.0, sleep=_no_sleep)
        options.update(kwargs)
        return RetryingFetcher(_client(router), "Source", logger=lines.append, rate_limiter=None, **options)

    @pytest.mark.asyncio
    async def test_retries_throttling_and_server_errors_then_succeeds(self):
        router = Router()
        router.add(
            lambda request: True,
            httpx.Response(429, headers={"Retry-After": "4"}),
            httpx.ConnectError("reset"),
            httpx.Response(200, content=b"ok"),
        )
        waits: list[float] = []

        async def sleep(delay):
            waits.append(delay)

        lines: list[str] = []
        fetcher = self._fetcher(router, lines, sleep=sleep, headers={"x-api-key": "k"})
        assert await fetcher.fetch("https://source.test/x", "search", {"q": "a b"}) == b"ok"
        assert waits == [4.0, 2.0]
        assert router.requests[0].url.params["q"] == "a b"
        assert router.requests[0].headers["x-api-key"] == "k"
        assert lines[0].startswith("Source search attempt 1 failed")

    @pytest.mark.asyncio
    async def test_a_permanent_rejection_is_an_extraction_error_without_retrying(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(400))
        with pytest.raises(ExtractionError, match="Source rejected the search with status 400"):
            await self._fetcher(router, []).fetch("https://source.test/x", "search")
        assert len(router.requests) == 1

    @pytest.mark.asyncio
    async def test_an_optional_fetch_reads_a_permanent_rejection_as_unavailable(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(404))
        lines: list[str] = []
        assert await self._fetcher(router, lines).fetch_optional("https://source.test/x", "PDF download") is None
        assert lines == ["Source PDF download unavailable: status 404"]

    @pytest.mark.asyncio
    async def test_exhausted_retries_raise_upstream_error(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(503))
        lines: list[str] = []
        with pytest.raises(UpstreamError, match="Source search failed after 2 attempts"):
            await self._fetcher(router, lines, max_retries=2).fetch("https://source.test/x", "search")
        assert lines[-1].startswith("Source search failed after 2 attempts")

    @pytest.mark.asyncio
    async def test_each_attempt_enters_the_rate_limiter(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(500), httpx.Response(200))
        limiter = CountingLimiter()
        fetcher = RetryingFetcher(
            _client(router), "Source", max_retries=3, backoff_factor=1, max_retry_after=1, sleep=_no_sleep,
            logger=lambda _line: None, rate_limiter=limiter,
        )
        await fetcher.fetch("https://source.test/x", "search")
        assert limiter.entered == 2

    @pytest.mark.parametrize(
        ("kwargs", "message"), [({"max_retries": 0}, "positive"), ({"max_retry_after": -1}, "negative")]
    )
    def test_rejects_invalid_retry_settings(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            self._fetcher(Router(), [], **kwargs)


def _work(number: int, **overrides):
    work = {
        "id": f"https://openalex.org/W{number}",
        "display_name": f"Work {number}",
        "abstract_inverted_index": {"Dark": [0], "matter": [1, 3], "and": [2]},
        "doi": f"https://doi.org/10.1/{number}",
        "publication_date": "2024-03-07",
        "publication_year": 2024,
        "authorships": [{"author": {"display_name": "Ada"}}, {"author": {}}, "bad"],
        "topics": [{"display_name": "Galaxies"}, {"display_name": ""}],
        "primary_location": {"source": {"display_name": "ApJ"}, "landing_page_url": "https://journal.test/w"},
        "referenced_works": ["https://openalex.org/W9", ""],
        "best_oa_location": {"pdf_url": f"https://oa.test/{number}.pdf"},
    }
    work.update(overrides)
    return work


class TestOpenAlexExtractor:
    @pytest.mark.asyncio
    async def test_search_maps_offsets_to_pages_and_drops_works_before_the_offset(self):
        router = Router()
        listing = {"meta": {}, "results": [_work(1), _work(2), _work(3)]}
        router.add(lambda request: True, httpx.Response(200, json=listing))
        extractor = AsyncOpenAlexExtractor(
            _client(router), filter="type:article", mailto="me@example.org", api_key="key", sleep=_no_sleep
        )
        payload = await extractor.search("dark matter", 3, 4)
        params = router.requests[0].url.params
        assert (params["search"], params["per-page"], params["page"]) == ("dark matter", "3", "2")
        assert (params["filter"], params["sort"], params["mailto"], params["api_key"]) == (
            "type:article", "publication_date:desc", "me@example.org", "key"
        )
        records, entries = extractor.parse_listing(payload, set())
        assert [record.record_id for record in records] == ["W2", "W3"]
        assert entries == 2

    @pytest.mark.asyncio
    async def test_an_empty_query_and_no_sort_send_neither(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(200, json={"results": "odd"}))
        extractor = AsyncOpenAlexExtractor(_client(router), sort=None, sleep=_no_sleep)
        payload = await extractor.search("", 500, 0)
        params = router.requests[0].url.params
        assert "search" not in params
        assert "sort" not in params
        assert params["per-page"] == "200"
        with pytest.raises(MalformedResponseError, match="no results list"):
            extractor.parse_listing(payload, set())

    @pytest.mark.asyncio
    async def test_offsets_past_ten_thousand_are_an_empty_listing(self):
        lines: list[str] = []
        extractor = AsyncOpenAlexExtractor(_client(Router()), logger=lines.append)
        assert extractor.parse_listing(await extractor.search("q", 200, 10_000), set()) == ([], 0)
        assert "first 10,000 results" in lines[0]

    def test_parse_listing_builds_records_with_metadata(self):
        extractor = AsyncOpenAlexExtractor(_client(Router()))
        payload = json.dumps(
            {"results": [_work(1), _work(2), {"id": None}, "junk", _work(3, doi=None, primary_location=None)]}
        ).encode()
        records, entries = extractor.parse_listing(payload, {"W2"})
        assert entries == 5
        first = records[0]
        assert (first.record_id, first.title, first.abstract) == ("W1", "Work 1", "Dark matter and matter")
        assert first.source_url == "https://doi.org/10.1/1"
        assert first.metadata == {
            "authors": ["Ada"],
            "categories": ["Galaxies"],
            "published": "2024-03-07",
            "year": "2024",
            "doi": "10.1/1",
            "venue": "ApJ",
            "references": ["W9"],
            "pdf_url": "https://oa.test/1.pdf",
        }
        assert records[1].source_url is None
        assert "doi" not in records[1].metadata
        assert "venue" not in records[1].metadata

    def test_parse_listing_uses_the_landing_page_and_tolerates_sparse_works(self):
        extractor = AsyncOpenAlexExtractor(_client(Router()))
        sparse = {"id": "W5", "title": "Fallback title", "doi": "", "publication_year": True,
                  "primary_location": {"landing_page_url": "https://landing.test"}, "best_oa_location": {}}
        records, _ = extractor.parse_listing(json.dumps({"results": [sparse]}).encode(), set())
        assert records[0].title == "Fallback title"
        assert records[0].source_url == "https://landing.test"
        assert records[0].metadata == {"authors": [], "categories": []}

    @pytest.mark.parametrize("payload", [b"not json", b"[1]"])
    def test_unreadable_listings_are_malformed(self, payload):
        with pytest.raises(MalformedResponseError):
            AsyncOpenAlexExtractor(_client(Router())).parse_listing(payload, set())

    def test_reconstruct_abstract_ignores_invalid_positions(self):
        assert reconstruct_abstract({"a": [1], "b": [0, -1, True, "x"], "c": "bad"}) == "b a"
        assert reconstruct_abstract(None) == ""

    @pytest.mark.asyncio
    async def test_full_text_comes_from_the_open_access_pdf_trimmed_of_references(self):
        router = Router()
        router.add(lambda request: request.url.host == "oa.test", httpx.Response(200, content=b"%PDF"))
        extractor = AsyncOpenAlexExtractor(_client(router), StubPdfParser(), sleep=_no_sleep)
        record = RawRecord("W1", "t", "abstract", metadata={"pdf_url": "https://oa.test/1.pdf"})
        assert await extractor.fetch_full_text(record) == "PDF body."

    @pytest.mark.asyncio
    async def test_full_text_falls_back_to_the_abstract(self):
        router = Router()
        router.add(lambda request: request.url.path == "/missing.pdf", httpx.Response(404))
        router.add(lambda request: request.url.path == "/bad.pdf", httpx.Response(200, content=b"x"))
        lines: list[str] = []
        with_parser = AsyncOpenAlexExtractor(_client(router), StubPdfParser(error=True), logger=lines.append)
        without_parser = AsyncOpenAlexExtractor(_client(router))
        missing = RawRecord("W1", "t", "abstract", metadata={"pdf_url": "https://oa.test/missing.pdf"})
        unreadable = RawRecord("W2", "t", "abstract", metadata={"pdf_url": "https://oa.test/bad.pdf"})
        assert await with_parser.fetch_full_text(missing) == "abstract"
        assert await with_parser.fetch_full_text(unreadable) == "abstract"
        assert await with_parser.fetch_full_text(RawRecord("W3", "t", "abstract")) == "abstract"
        assert await without_parser.fetch_full_text(unreadable) == "abstract"
        assert "PDF unusable for 'W2': not a pdf" in lines

    @pytest.mark.asyncio
    async def test_a_pdf_whose_text_is_blank_falls_back_to_the_abstract(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(200, content=b"%PDF"))
        extractor = AsyncOpenAlexExtractor(_client(router), StubPdfParser(text="  "))
        record = RawRecord("W1", "t", "abstract", metadata={"pdf_url": "https://oa.test/1.pdf"})
        assert await extractor.fetch_full_text(record) == "abstract"


def _paper(paper_id: str, **overrides):
    paper = {
        "paperId": paper_id,
        "title": f"Paper {paper_id}",
        "abstract": "An abstract.",
        "year": 2023,
        "publicationDate": "2023-05-01",
        "authors": [{"name": "Grace"}, {"name": ""}, "bad"],
        "externalIds": {"DOI": "10.2/x", "ArXiv": "2305.00001", "PubMed": 123, "MAG": None},
        "url": f"https://www.semanticscholar.org/paper/{paper_id}",
        "venue": "MNRAS",
        "fieldsOfStudy": ["Physics", "Physics", 7],
        "s2FieldsOfStudy": [{"category": "Physics"}, {"category": "Astronomy"}, "bad"],
        "openAccessPdf": {"url": "https://oa.test/p.pdf"},
    }
    paper.update(overrides)
    return paper


class TestSemanticScholarExtractor:
    @pytest.mark.asyncio
    async def test_search_sends_offset_limit_fields_filters_and_key(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(200, json={"total": 2, "data": [_paper("a")]}))
        extractor = AsyncSemanticScholarExtractor(
            _client(router), api_key="secret", year="2020-", fields_of_study="Physics", sleep=_no_sleep
        )
        payload = await extractor.search("ultra diffuse", 500, 950)
        request = router.requests[0]
        assert request.headers["x-api-key"] == "secret"
        params = request.url.params
        assert (params["query"], params["offset"], params["limit"]) == ("ultra diffuse", "950", "50")
        assert (params["year"], params["fieldsOfStudy"]) == ("2020-", "Physics")
        assert "openAccessPdf" in params["fields"]
        assert extractor.parse_listing(payload, set())[1] == 1

    @pytest.mark.asyncio
    async def test_offsets_past_the_first_thousand_are_an_empty_listing_without_a_request(self):
        router = Router()
        lines: list[str] = []
        extractor = AsyncSemanticScholarExtractor(_client(router), logger=lines.append)
        assert extractor.parse_listing(await extractor.search("q", 100, 1000), set()) == ([], 0)
        assert router.requests == []
        assert "first 1000 results" in lines[0]

    def test_parse_listing_builds_records_with_metadata(self):
        extractor = AsyncSemanticScholarExtractor(_client(Router()))
        payload = json.dumps({"data": [_paper("a"), _paper("b"), {"paperId": 5}, "junk"]}).encode()
        records, entries = extractor.parse_listing(payload, {"b"})
        assert entries == 4
        assert [record.record_id for record in records] == ["a"]
        assert records[0].source_url == "https://www.semanticscholar.org/paper/a"
        assert records[0].metadata == {
            "authors": ["Grace"],
            "categories": ["Physics", "Astronomy"],
            "published": "2023-05-01",
            "year": "2023",
            "venue": "MNRAS",
            "doi": "10.2/x",
            "arxiv_id": "2305.00001",
            "pmid": "123",
            "pdf_url": "https://oa.test/p.pdf",
        }

    def test_sparse_papers_and_a_response_without_data(self):
        extractor = AsyncSemanticScholarExtractor(_client(Router()))
        sparse = {"paperId": "s", "title": None, "abstract": None, "url": None, "year": False, "openAccessPdf": None}
        records, _ = extractor.parse_listing(json.dumps({"data": [sparse]}).encode(), set())
        assert (records[0].title, records[0].abstract, records[0].source_url) == ("", "", None)
        assert records[0].metadata == {"authors": [], "categories": []}
        assert extractor.parse_listing(b'{"total": 0}', set()) == ([], 0)

    @pytest.mark.parametrize("payload", [b"<html>", b"[]", b'{"data": {}}'])
    def test_unreadable_listings_are_malformed(self, payload):
        with pytest.raises(MalformedResponseError):
            AsyncSemanticScholarExtractor(_client(Router())).parse_listing(payload, set())

    @pytest.mark.asyncio
    async def test_full_text_from_the_open_access_pdf_or_the_abstract(self):
        router = Router()
        router.add(lambda request: request.url.path == "/p.pdf", httpx.Response(200, content=b"%PDF"))
        extractor = AsyncSemanticScholarExtractor(_client(router), StubPdfParser(), sleep=_no_sleep)
        with_pdf = RawRecord("a", "t", "abstract", metadata={"pdf_url": "https://oa.test/p.pdf"})
        missing = RawRecord("b", "t", "abstract", metadata={"pdf_url": "https://oa.test/gone.pdf"})
        assert await extractor.fetch_full_text(with_pdf) == "PDF body."
        assert await extractor.fetch_full_text(missing) == "abstract"
        assert await extractor.fetch_full_text(RawRecord("c", "t", "abstract")) == "abstract"
        blank = AsyncSemanticScholarExtractor(_client(router), StubPdfParser(text=""))
        assert await blank.fetch_full_text(with_pdf) == "abstract"


EFETCH = b"""<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2024//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_240101.dtd">
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">38000001</PMID>
    <Article>
      <Journal><JournalIssue><PubDate><Year>2024</Year><Month>Feb</Month></PubDate></JournalIssue>
        <Title>Nature Astronomy</Title></Journal>
      <ArticleTitle>Dwarf <i>galaxies</i></ArticleTitle>
      <Abstract>
        <AbstractText Label="BACKGROUND">Why.</AbstractText>
        <AbstractText Label="RESULTS">What.</AbstractText>
        <AbstractText/>
      </Abstract>
      <AuthorList>
        <Author><LastName>Rubin</LastName><ForeName>Vera</ForeName></Author>
        <Author><CollectiveName>Survey Team</CollectiveName></Author>
        <Author/>
      </AuthorList>
      <ArticleDate DateType="Electronic"><Year>2024</Year><Month>01</Month><Day>15</Day></ArticleDate>
    </Article>
    <MeshHeadingList><MeshHeading><DescriptorName>Galaxies</DescriptorName></MeshHeading></MeshHeadingList>
  </MedlineCitation>
  <PubmedData><ArticleIdList>
    <ArticleId IdType="pubmed">38000001</ArticleId>
    <ArticleId IdType="doi">10.3/abc</ArticleId>
    <ArticleId IdType="pmc">PMC123</ArticleId>
  </ArticleIdList></PubmedData>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation><PMID>38000002</PMID>
    <Article><Journal><JournalIssue>
      <PubDate><MedlineDate>2019 Dec-2020 Jan</MedlineDate></PubDate>
    </JournalIssue></Journal>
      <ArticleTitle>Second</ArticleTitle></Article>
  </MedlineCitation>
</PubmedArticle>
<PubmedArticle><MedlineCitation><PMID></PMID></MedlineCitation></PubmedArticle>
<PubmedArticle><PubmedData/></PubmedArticle>
</PubmedArticleSet>
"""


class TestPubMedExtractor:
    def _router(self, ids, efetch=EFETCH):
        router = Router()
        router.add(
            lambda request: request.url.path.endswith("esearch.fcgi"),
            httpx.Response(200, json={"esearchresult": {"idlist": ids}}),
        )
        router.add(lambda request: request.url.path.endswith("efetch.fcgi"), httpx.Response(200, content=efetch))
        return router

    @pytest.mark.asyncio
    async def test_search_runs_esearch_then_efetch_and_counts_the_ids(self):
        router = self._router(["38000001", "38000002", "38000003", " "])
        extractor = AsyncPubMedExtractor(_client(router), api_key="k", tool="sci-etl", email="me@example.org")
        payload = await extractor.search("galaxies[mh]", 20, 40)
        search, fetch = router.requests
        assert search.url.params["term"] == "galaxies[mh]"
        assert (search.url.params["retstart"], search.url.params["retmax"], search.url.params["sort"]) == (
            "40", "20", "pub_date"
        )
        assert (search.url.params["api_key"], search.url.params["tool"], search.url.params["email"]) == (
            "k", "sci-etl", "me@example.org"
        )
        assert fetch.url.params["id"] == "38000001,38000002,38000003"
        records, entries = extractor.parse_listing(payload, {"38000002"})
        assert entries == 3
        assert [record.record_id for record in records] == ["38000001"]

    def test_records_carry_title_labelled_abstract_and_metadata(self):
        extractor = AsyncPubMedExtractor(_client(Router()))
        listing = b'<pubmed-listing entries="4">' + EFETCH.split(b"?>", 1)[1].split(b">", 1)[1] + b"</pubmed-listing>"
        records, _ = extractor.parse_listing(listing, set())
        first, second = records
        assert first.title == "Dwarf galaxies"
        assert first.abstract == "BACKGROUND: Why.\nRESULTS: What."
        assert first.source_url == "https://pubmed.ncbi.nlm.nih.gov/38000001/"
        assert first.metadata == {
            "authors": ["Vera Rubin", "Survey Team"],
            "categories": ["Galaxies"],
            "published": "2024-01-15",
            "year": "2024",
            "journal": "Nature Astronomy",
            "doi": "10.3/abc",
            "pmcid": "PMC123",
        }
        assert second.metadata == {"authors": [], "categories": [], "published": "2019", "year": "2019"}

    @pytest.mark.asyncio
    async def test_no_ids_is_an_empty_listing_without_efetch(self):
        router = self._router([])
        extractor = AsyncPubMedExtractor(_client(router), sort=None)
        payload = await extractor.search("nothing", 20, 0)
        assert "sort" not in router.requests[0].url.params
        assert len(router.requests) == 1
        assert extractor.parse_listing(payload, set()) == ([], 0)

    @pytest.mark.asyncio
    async def test_offsets_past_the_first_ten_thousand_are_an_empty_listing(self):
        lines: list[str] = []
        extractor = AsyncPubMedExtractor(_client(Router()), logger=lines.append)
        assert extractor.parse_listing(await extractor.search("q", 20, 10_000), set()) == ([], 0)
        assert "first 10,000 results" in lines[0]

    @pytest.mark.parametrize(
        "payload", [b'{"esearchresult": {}}', b"not json", b'{"esearchresult": {"idlist": "x"}}']
    )
    @pytest.mark.asyncio
    async def test_an_unreadable_esearch_response_is_malformed(self, payload):
        router = Router()
        router.add(lambda request: True, httpx.Response(200, content=payload))
        with pytest.raises(MalformedResponseError):
            await AsyncPubMedExtractor(_client(router)).search("q", 5, 0)

    @pytest.mark.parametrize("payload", [b"<oops", b"<PubmedArticleSet/>", b'<pubmed-listing entries="many"/>'])
    def test_unreadable_listings_are_malformed(self, payload):
        with pytest.raises(MalformedResponseError):
            AsyncPubMedExtractor(_client(Router())).parse_listing(payload, set())

    @pytest.mark.parametrize(
        ("pub_date", "expected"),
        [
            (b"<Year>2021</Year><Month>13</Month>", "2021"),
            (b"<Year>2021</Year><Month>Sept</Month><Day>40</Day>", "2021-09"),
            (b"<Year>2021</Year><Month>3</Month><Day>9</Day>", "2021-03-09"),
            (b"<Year>21</Year><MedlineDate>Spring</MedlineDate>", None),
        ],
    )
    def test_publication_dates(self, pub_date, expected):
        article = (
            b"<pubmed-listing entries='1'><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><Journal>"
            b"<JournalIssue><PubDate>" + pub_date + b"</PubDate></JournalIssue></Journal>"
            b"<ArticleDate><Year>none</Year></ArticleDate></Article></MedlineCitation></PubmedArticle>"
            b"</pubmed-listing>"
        )
        records, _ = AsyncPubMedExtractor(_client(Router())).parse_listing(article, set())
        assert records[0].metadata.get("published") == expected

    def test_an_article_without_a_journal_issue_date(self):
        article = (
            b"<pubmed-listing entries='1'><PubmedArticle><MedlineCitation><PMID>1</PMID>"
            b"<Article><Journal/></Article></MedlineCitation></PubmedArticle></pubmed-listing>"
        )
        records, _ = AsyncPubMedExtractor(_client(Router())).parse_listing(article, set())
        assert "published" not in records[0].metadata

    @pytest.mark.asyncio
    async def test_full_text_is_read_from_pubmed_central_as_jats(self):
        router = Router()
        router.add(lambda request: request.url.params.get("db") == "pmc", httpx.Response(200, content=JATS))
        extractor = AsyncPubMedExtractor(_client(router))
        text = await extractor.fetch_full_text(RawRecord("1", "t", "a", metadata={"pmcid": "PMC123"}))
        assert router.requests[0].url.params["id"] == "123"
        assert text.startswith("Dark matter in ultra-diffuse galaxies\n\nBackground")
        assert "Introduction" in text

    @pytest.mark.asyncio
    async def test_full_text_falls_back_to_the_abstract(self):
        router = Router()
        router.add(lambda request: request.url.params.get("id") == "1", httpx.Response(200, content=b"<oops"))
        router.add(
            lambda request: request.url.params.get("id") == "2",
            httpx.Response(200, content=b"<pmc-articleset><article><front/></article></pmc-articleset>"),
        )
        router.add(lambda request: request.url.params.get("id") == "3", httpx.Response(400))
        lines: list[str] = []
        extractor = AsyncPubMedExtractor(_client(router), logger=lines.append)
        for pmcid in ("PMC1", "PMC2", "PMC3"):
            assert await extractor.fetch_full_text(RawRecord("9", "t", "abstract", metadata={"pmcid": pmcid})) == (
                "abstract"
            )
        assert await extractor.fetch_full_text(RawRecord("9", "t", "abstract")) == "abstract"
        assert any("PMC full text unusable for '9'" in line for line in lines)
        assert "PMC has no full text for '9'" in lines

    @pytest.mark.asyncio
    async def test_a_custom_full_text_parser_is_used_as_is(self):
        router = Router()
        router.add(lambda request: True, httpx.Response(200, content=b"<x/>"))
        record = RawRecord("1", "t", "abstract", metadata={"pmcid": "PMC5"})
        assert await AsyncPubMedExtractor(_client(router), full_text_parser=StubPdfParser("custom")).fetch_full_text(
            record
        ) == "custom"
        blank = AsyncPubMedExtractor(_client(router), full_text_parser=StubPdfParser(""))
        assert await blank.fetch_full_text(record) == "abstract"
