from __future__ import annotations

import httpx
import pytest

from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.extractors.openalex_async import AsyncOpenAlexExtractor
from sci_etl_core.extractors.pubmed_async import AsyncPubMedExtractor
from sci_etl_core.extractors.semantic_scholar_async import AsyncSemanticScholarExtractor
from sci_etl_core.parsers.base import Parser
from sci_etl_core.testing import ExtractorContract
from semantics.harness import Listing, records

LISTED = 5


class StubParser(Parser):
    def extract_text(self, content: bytes) -> str:
        return f"Full text: {content.decode()}"


async def _no_sleep(_delay):
    return None


def _window(request: httpx.Request, offset_key: str, size_key: str) -> range:
    offset = int(request.url.params[offset_key])
    return range(offset, min(offset + int(request.url.params[size_key]), LISTED))


def _arxiv(request: httpx.Request) -> httpx.Response:
    if request.url.host == "arxiv.org":
        return httpx.Response(200, content=b"source of " + request.url.path.encode())
    entries = "".join(
        f"<entry><id>http://arxiv.org/abs/2401.0000{index}v1</id>"
        f"<title>Paper {index}</title><summary>Abstract {index}.</summary></entry>"
        for index in _window(request, "start", "max_results")
    )
    return httpx.Response(200, content=f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode())


def _openalex(request: httpx.Request) -> httpx.Response:
    cursor = request.url.params["cursor"]
    offset = 0 if cursor == "*" else int(cursor.removeprefix("page-"))
    end = min(offset + int(request.url.params["per-page"]), LISTED)
    results = [
        {"id": f"https://openalex.org/W{index}", "display_name": f"Paper {index}"} for index in range(offset, end)
    ]
    next_cursor = f"page-{end}" if end < LISTED else None
    return httpx.Response(200, json={"results": results, "meta": {"next_cursor": next_cursor}})


def _pubmed(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("esearch.fcgi"):
        ids = [str(1000 + index) for index in _window(request, "retstart", "retmax")]
        return httpx.Response(200, json={"esearchresult": {"count": str(LISTED), "idlist": ids}})
    articles = "".join(
        f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID>"
        f"<Article><ArticleTitle>Paper {pmid}</ArticleTitle></Article></MedlineCitation></PubmedArticle>"
        for pmid in request.url.params["id"].split(",")
    )
    return httpx.Response(200, content=f"<PubmedArticleSet>{articles}</PubmedArticleSet>".encode())


def _semantic_scholar(request: httpx.Request) -> httpx.Response:
    papers = [{"paperId": f"paper-{index}", "title": f"Paper {index}"} for index in _window(request, "offset", "limit")]
    return httpx.Response(200, json={"total": LISTED, "data": papers})


def _unavailable(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _arxiv_extractor(handler) -> AsyncArxivExtractor:
    return AsyncArxivExtractor(
        _client(handler), StubParser(), StubParser(), max_retries=1, sleep_before_search=0.0, sleep=_no_sleep
    )


class TestAsyncArxivExtractor(ExtractorContract):
    @pytest.fixture
    def make_extractor(self):
        return lambda: _arxiv_extractor(_arxiv)

    @pytest.fixture
    def make_unavailable_extractor(self):
        return lambda: _arxiv_extractor(_unavailable)


class TestAsyncOpenAlexExtractor(ExtractorContract):
    @pytest.fixture
    def make_extractor(self):
        return lambda: AsyncOpenAlexExtractor(_client(_openalex))

    @pytest.fixture
    def make_unavailable_extractor(self):
        return lambda: AsyncOpenAlexExtractor(_client(_unavailable), max_retries=1, sleep=_no_sleep)


class TestAsyncPubMedExtractor(ExtractorContract):
    @pytest.fixture
    def make_extractor(self):
        return lambda: AsyncPubMedExtractor(_client(_pubmed))

    @pytest.fixture
    def make_unavailable_extractor(self):
        return lambda: AsyncPubMedExtractor(_client(_unavailable), max_retries=1, sleep=_no_sleep)


class TestAsyncSemanticScholarExtractor(ExtractorContract):
    page_size = 3

    @pytest.fixture
    def make_extractor(self):
        return lambda: AsyncSemanticScholarExtractor(_client(_semantic_scholar))

    @pytest.fixture
    def make_unavailable_extractor(self):
        return lambda: AsyncSemanticScholarExtractor(_client(_unavailable), max_retries=1, sleep=_no_sleep)


class TestOffsetListingDouble(ExtractorContract):
    @pytest.fixture
    def make_extractor(self):
        listed = records("a", "b", "c", "d", "e")
        return lambda: Listing(listed)
