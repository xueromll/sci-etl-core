from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx

from sci_etl_core.exceptions import MalformedResponseError
from sci_etl_core.extractors._http import RetryingFetcher, parse_document
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.reference_trimmer import trim_after_references
from sci_etl_core.rate_limiter import RateLimiting

_FIELDS = (
    "paperId,title,abstract,year,publicationDate,authors,externalIds,url,venue,fieldsOfStudy,"
    "s2FieldsOfStudy,openAccessPdf"
)
_MAX_LIMIT = 100
_MAX_RESULTS = 1000


class AsyncSemanticScholarExtractor(AsyncExtractor):
    """Page through Semantic Scholar's relevance search for papers.

    Each record's ``record_id`` is the Semantic Scholar paper id, and its
    ``metadata`` holds ``authors``, ``categories`` (fields of study),
    ``published``, ``year``, ``venue``, ``doi``, ``arxiv_id`` and ``pmid`` when
    known, and ``pdf_url`` for an open-access PDF.

    Without an ``api_key``, requests share Semantic Scholar's public rate
    limit, so pass a ``rate_limiter``, for example one request per second.
    Full text comes from the open-access PDF when a ``pdf_parser`` is given,
    and the abstract otherwise. The injected ``client`` is borrowed and never
    closed.
    """

    API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(
        self,
        client: httpx.AsyncClient,
        pdf_parser: Parser | None = None,
        *,
        api_key: str | None = None,
        year: str | None = None,
        fields_of_study: str | None = None,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        max_retry_after: float = 60.0,
        sleep: Any = asyncio.sleep,
        logger: Callable[[str], None] | None = None,
        rate_limiter: RateLimiting | None = None,
    ) -> None:
        """Configure the extractor.

        ``year`` and ``fields_of_study`` are passed as Semantic Scholar's
        filters of the same names, such as ``"2020-"`` and ``"Physics"``. The
        relevance search returns at most the first 1,000 results, 100 at a
        time, so ``search`` returns an empty listing beyond them.

        Raises:
            ValueError: ``max_retries`` is less than 1 or ``max_retry_after`` is
                negative.
        """
        self._log = logger or (lambda _msg: None)
        self._fetcher = RetryingFetcher(
            client,
            "Semantic Scholar",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            max_retry_after=max_retry_after,
            sleep=sleep,
            logger=self._log,
            rate_limiter=rate_limiter,
            headers={"x-api-key": api_key} if api_key else None,
        )
        self._pdf_parser = pdf_parser
        self._filters = {"year": year, "fieldsOfStudy": fields_of_study}

    async def search(self, query: str, max_results: int, start_index: int) -> bytes:
        """Fetch the papers at offsets ``start_index`` to ``start_index + max_results``.

        Raises:
            UpstreamError: Every attempt failed transiently.
            ExtractionError: Semantic Scholar rejected the request.
        """
        limit = min(max(1, max_results), _MAX_LIMIT, _MAX_RESULTS - start_index)
        if limit <= 0:
            self._log(f"Semantic Scholar only returns the first {_MAX_RESULTS} results; {start_index} is past them")
            return b'{"data": []}'
        params: dict[str, Any] = {"query": query, "offset": start_index, "limit": limit, "fields": _FIELDS}
        params.update({name: value for name, value in self._filters.items() if value})
        return await self._fetcher.fetch(self.API_URL, "search", params)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse a listing page, skipping papers already seen or without an id.

        A response without ``data``, which Semantic Scholar sends when nothing
        matches, is an empty listing.

        Raises:
            MalformedResponseError: The payload is not a JSON object, or its
                ``data`` is not a list.
        """
        try:
            decoded = json.loads(raw_listing)
        except ValueError as exc:
            raise MalformedResponseError("Semantic Scholar response is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise MalformedResponseError("Semantic Scholar response is not a JSON object")
        papers = decoded.get("data", [])
        if not isinstance(papers, list):
            raise MalformedResponseError("Semantic Scholar listing data is not a list")
        records: list[RawRecord] = []
        for paper in papers:
            if not isinstance(paper, dict):
                continue
            record_id = paper.get("paperId")
            if not isinstance(record_id, str) or not record_id or record_id in seen_ids:
                continue
            records.append(
                RawRecord(
                    record_id=record_id,
                    title=str(paper.get("title") or ""),
                    abstract=str(paper.get("abstract") or ""),
                    source_url=paper.get("url") if isinstance(paper.get("url"), str) else None,
                    metadata=self._metadata(paper),
                )
            )
        return records, len(papers)

    async def fetch_full_text(self, record: RawRecord) -> str:
        """Return the open-access PDF's text, or the abstract when there is no usable PDF.

        Raises:
            UpstreamError: The PDF download failed transiently.
        """
        pdf_url = record.metadata.get("pdf_url")
        if self._pdf_parser is None or not isinstance(pdf_url, str) or not pdf_url:
            return record.abstract
        content = await self._fetcher.fetch_optional(pdf_url, f"PDF download for {record.record_id!r}")
        if content is None:
            return record.abstract
        text = await parse_document(self._pdf_parser, content, "PDF", record, self._log)
        return (trim_after_references(text) or text) if text else record.abstract

    @staticmethod
    def _metadata(paper: dict[str, Any]) -> dict[str, Any]:
        authors = [
            name
            for author in paper.get("authors") or []
            if isinstance(author, dict) and (name := str(author.get("name") or "").strip())
        ]
        categories: list[str] = []
        for field in paper.get("fieldsOfStudy") or []:
            if isinstance(field, str) and field and field not in categories:
                categories.append(field)
        for field in paper.get("s2FieldsOfStudy") or []:
            category = field.get("category") if isinstance(field, dict) else None
            if isinstance(category, str) and category and category not in categories:
                categories.append(category)
        metadata: dict[str, Any] = {"authors": authors, "categories": categories}
        published = paper.get("publicationDate")
        if isinstance(published, str) and published:
            metadata["published"] = published
        year = paper.get("year")
        if isinstance(year, int) and not isinstance(year, bool):
            metadata["year"] = str(year)
        venue = paper.get("venue")
        if isinstance(venue, str) and venue:
            metadata["venue"] = venue
        external = paper.get("externalIds")
        if isinstance(external, dict):
            for source_key, metadata_key in (("DOI", "doi"), ("ArXiv", "arxiv_id"), ("PubMed", "pmid")):
                value = external.get(source_key)
                if value:
                    metadata[metadata_key] = str(value)
        pdf = paper.get("openAccessPdf")
        if isinstance(pdf, dict) and isinstance(pdf.get("url"), str) and pdf["url"]:
            metadata["pdf_url"] = pdf["url"]
        return metadata
