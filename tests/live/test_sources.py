"""Smoke tests against the real sources, run nightly by the Live workflow.

Deselected by default; run them with ``pytest -m live tests/live``. They catch
upstream payload changes that the offline suite cannot see. Optional keys are
read from ``NCBI_API_KEY``, ``SEMANTIC_SCHOLAR_API_KEY``, and
``OPENALEX_MAILTO``; without them the sources allow fewer requests, and the
tests still run. A source that keeps answering ``429`` to an unkeyed run is
skipped rather than failed, because the shared unkeyed pool is outside the
library's control.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx
import pytest
import pytest_asyncio

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncOpenAlexExtractor,
    AsyncPubMedExtractor,
    AsyncSemanticScholarExtractor,
)
from sci_etl_core.exceptions import UpstreamError
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.http_async import build_async_client
from sci_etl_core.models import ListingPage
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

pytestmark = pytest.mark.live

PAGE_SIZE = 5
UNKEYED_RETRIES = 6
FULL_TEXT_ATTEMPTS = 3


@dataclass(frozen=True)
class Source:
    name: str
    query: str
    build: Callable[[httpx.AsyncClient], AsyncExtractor]
    key_variable: str | None = None

    def runs_unkeyed(self) -> bool:
        return self.key_variable is not None and not os.environ.get(self.key_variable)


SOURCES = [
    Source(
        "arxiv",
        'cat:astro-ph.GA AND abs:"ultra-diffuse"',
        lambda client: AsyncArxivExtractor(client, PdfPlumberParser(), LatexTarballParser()),
    ),
    Source(
        "pubmed",
        "ultra-diffuse galaxies OR CRISPR",
        lambda client: AsyncPubMedExtractor(client, api_key=os.environ.get("NCBI_API_KEY") or None),
        key_variable="NCBI_API_KEY",
    ),
    Source(
        "semantic_scholar",
        "ultra-diffuse galaxies",
        lambda client: AsyncSemanticScholarExtractor(
            client,
            api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or None,
            max_retries=UNKEYED_RETRIES,
            backoff_factor=3.0,
            rate_limiter=build_rate_limiter(max_rate=1, time_period=1.0),
        ),
        key_variable="SEMANTIC_SCHOLAR_API_KEY",
    ),
    Source(
        "openalex",
        "ultra-diffuse galaxies",
        lambda client: AsyncOpenAlexExtractor(client, mailto=os.environ.get("OPENALEX_MAILTO") or None),
    ),
]


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    http_client = build_async_client(timeout=60.0)
    try:
        yield http_client
    finally:
        await http_client.aclose()


def _rate_limited(error: UpstreamError) -> bool:
    cause = error.__cause__
    return isinstance(cause, UpstreamError) and str(cause).endswith("status 429")


async def _first_page(extractor: AsyncExtractor, source: Source) -> ListingPage:
    try:
        return await extractor.fetch_page(source.query, None, PAGE_SIZE)
    except UpstreamError as error:
        if source.runs_unkeyed() and _rate_limited(error):
            pytest.skip(f"{source.name} kept rate limiting the unkeyed pool; set {source.key_variable} to test it")
        raise


@pytest.mark.asyncio
@pytest.mark.parametrize("source", SOURCES, ids=[source.name for source in SOURCES])
async def test_source_lists_records_with_the_promised_metadata_and_full_text(client, source):
    extractor = source.build(client)

    page = await _first_page(extractor, source)
    records, entries = page.records, page.entries

    assert entries >= 1
    assert records, f"{source.name} listed {entries} entries but none parsed into a record"
    for record in records:
        assert record.record_id.strip()
        assert record.title.strip()
        assert "authors" in record.metadata, record.record_id
        assert "categories" in record.metadata, record.record_id
        if "published" in record.metadata:
            assert "year" in record.metadata, record.record_id

    texts = [await extractor.fetch_full_text(record) for record in records[:FULL_TEXT_ATTEMPTS]]
    assert any(text.strip() for text in texts), f"{source.name} returned no full text or abstract"
