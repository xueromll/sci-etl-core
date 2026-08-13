from __future__ import annotations

import asyncio
import re
from typing import Any, Callable

import httpx
from bs4 import BeautifulSoup

from sci_etl_core.exceptions import ExtractionError, MalformedResponseError, UpstreamError
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.reference_trimmer import trim_after_references

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_SERVER_ERROR_FLOOR = 500
_VERSION_SUFFIX = re.compile(r"v\d+$")
_FEED_ROOT = "feed"


class AsyncArxivExtractor(AsyncExtractor):
    API_URL = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        client: httpx.AsyncClient,
        pdf_parser: Parser,
        latex_parser: Parser,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        sleep_before_search: float = 3.0,
        logger: Callable[[str], None] | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._client = client
        self._pdf_parser = pdf_parser
        self._latex_parser = latex_parser
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._sleep_before_search = sleep_before_search
        self._log = logger or (lambda _msg: None)
        self._sleep = sleep

    async def search(self, query: str, max_results: int, start_index: int) -> bytes:
        """Fetch one listing page, retrying transient faults.

        Raises:
            UpstreamError: Every attempt failed. A transport fault is never
                reported as an empty result.
        """
        params = {
            "search_query": query,
            "start": start_index,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        await self._sleep(self._sleep_before_search)

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.get(self.API_URL, params=params)
                if self._is_retryable(response.status_code):
                    last_error = ExtractionError(f"arXiv returned status {response.status_code}")
                    await self._sleep(self._backoff_factor**attempt)
                    continue
                response.raise_for_status()
                return response.content
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    await self._sleep(self._backoff_factor**attempt)

        message = f"arXiv search failed after {self._max_retries} attempts"
        self._log(f"{message}: {last_error!r}")
        raise UpstreamError(message) from last_error

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse an Atom listing, treating an unreadable payload as an error.

        Raises:
            MalformedResponseError: The payload is empty or lacks a feed root.
        """
        soup = self._parse_feed(raw_listing)
        entries = soup.find_all("entry")
        if not entries:
            return [], 0

        records: list[RawRecord] = []
        seen_base_ids: set[str] = set()
        for entry in entries:
            raw_id = entry.id.get_text(strip=True) if entry.id else ""
            record_id = self._normalize_id(raw_id)
            if record_id in seen_ids:
                continue
            base_id = self._strip_version(record_id)
            if base_id in seen_base_ids:
                continue
            seen_base_ids.add(base_id)
            html_link = next(
                (link.get("href") for link in entry.find_all("link") if "html" in link.get("href", "")),
                None,
            )
            records.append(
                RawRecord(
                    record_id=record_id,
                    title=entry.title.get_text(strip=True) if entry.title else "",
                    abstract=entry.summary.get_text(strip=True) if entry.summary else "",
                    source_url=html_link,
                )
            )
        return records, len(entries)

    @staticmethod
    def _is_retryable(status_code: int) -> bool:
        """Whether a status code warrants another attempt.

        Throttling and server-side faults are transient; every other 4xx is a
        permanent verdict about this URL and must not be retried.
        """
        return status_code in _RETRYABLE_STATUS or status_code >= _SERVER_ERROR_FLOOR

    @staticmethod
    def _parse_feed(raw_listing: bytes) -> BeautifulSoup:
        if not raw_listing or not raw_listing.strip():
            raise MalformedResponseError("arXiv listing payload was empty")
        soup = BeautifulSoup(raw_listing, "xml")
        if soup.find(_FEED_ROOT) is None:
            raise MalformedResponseError("arXiv listing payload is not a valid Atom feed")
        return soup

    def _normalize_id(self, raw_id: str) -> str:
        """Strip arXiv ``/abs/`` and ``/pdf/`` URL prefixes from a raw record id.

        The version marker (``v2``) is intentionally preserved so that a new
        version encountered in a later run is treated as an unseen record.
        """
        if "/abs/" in raw_id:
            return raw_id.split("/abs/")[-1]
        if "/pdf/" in raw_id:
            return raw_id.split("/pdf/")[-1].replace(".pdf", "")
        return raw_id

    def _strip_version(self, record_id: str) -> str:
        """Return the record id without its trailing arXiv version marker (``v2``)."""
        return _VERSION_SUFFIX.sub("", record_id)

    async def fetch_full_text(self, record: RawRecord) -> str:
        """Return the best-available full text, falling back to the abstract.

        The abstract is used only when every source answered that the artifact
        is permanently unavailable. A transport failure is raised instead, so
        the record stays unmarked and is retried on the next run.

        Raises:
            UpstreamError: At least one source failed transiently and no source
                yielded usable text.
        """
        if not record.record_id:
            return record.abstract

        failures: list[Exception] = []
        for fetch in (self._fetch_latex_source, self._fetch_pdf_text):
            try:
                text = await fetch(record.record_id)
            except UpstreamError as exc:
                failures.append(exc)
                continue
            if text:
                return trim_after_references(text) or text

        if failures:
            message = f"Full-text retrieval failed for {record.record_id!r}"
            raise UpstreamError(message) from failures[-1]
        return record.abstract

    async def _fetch_latex_source(self, arxiv_id: str) -> str | None:
        content = await self._get_bytes(
            f"https://arxiv.org/e-print/{arxiv_id}", label="LaTeX", record_id=arxiv_id
        )
        if content is None:
            return None
        return (await asyncio.to_thread(self._latex_parser.extract_text, content)) or None

    async def _fetch_pdf_text(self, arxiv_id: str) -> str | None:
        content = await self._get_bytes(
            f"https://arxiv.org/pdf/{arxiv_id}.pdf", label="PDF", record_id=arxiv_id
        )
        if content is None:
            return None
        return (await asyncio.to_thread(self._pdf_parser.extract_text, content)) or None

    async def _get_bytes(self, url: str, label: str, record_id: str) -> bytes | None:
        """Fetch a binary artifact, retrying only transient faults.

        Returns:
            The payload, or ``None`` when the source gave a fatal verdict such
            as ``404``, meaning the artifact will never exist at this URL.

        Raises:
            UpstreamError: Every retryable attempt was exhausted.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
            else:
                if response.status_code == httpx.codes.OK:
                    return response.content
                if not self._is_retryable(response.status_code):
                    self._log(
                        f"{label} unavailable for {record_id!r}: status {response.status_code}"
                    )
                    return None
                last_error = UpstreamError(
                    f"{label} fetch returned status {response.status_code}"
                )
            if attempt < self._max_retries - 1:
                await self._sleep(self._backoff_factor**attempt)

        message = f"{label} fetch failed for {record_id!r} after {self._max_retries} attempts"
        self._log(f"{message}: {last_error!r}")
        raise UpstreamError(message) from last_error
