"""Smoke tests against the real sources, run nightly by the Live workflow.

Deselected by default; run them with ``pytest -m live tests/live``. They catch
upstream payload changes that the offline suite cannot see. Optional keys are
read from ``NCBI_API_KEY``, ``SEMANTIC_SCHOLAR_API_KEY``, and
``OPENALEX_MAILTO``; without them the sources allow fewer requests, and the
tests still run.
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
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.http_async import build_async_client
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


@pytest.mark.asyncio
@pytest.mark.parametrize("source", SOURCES, ids=[source.name for source in SOURCES])
async def test_source_lists_records_with_the_promised_metadata_and_full_text(client, source):
    extractor = source.build(client)

    raw_listing = await extractor.search(source.query, PAGE_SIZE, 0)
    assert raw_listing, f"{source.name} returned no listing payload"
    records, entries = extractor.parse_listing(raw_listing, set())

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
