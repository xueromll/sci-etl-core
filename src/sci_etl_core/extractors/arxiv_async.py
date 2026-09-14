from __future__ import annotations

import asyncio
import re
from typing import Any, Callable

import httpx
from bs4 import BeautifulSoup

from sci_etl_core._retry_after import retry_after_from_headers, retry_delay
from sci_etl_core.exceptions import ExtractionError, MalformedResponseError, ParsingError, UpstreamError
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.reference_trimmer import trim_after_references

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_SERVER_ERROR_FLOOR = 500
_SUCCESS_FLOOR = 200
_SUCCESS_CEILING = 300
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
        max_retry_after: float = 60.0,
    ) -> None:
        """Configure the extractor.

        Between attempts the extractor waits ``backoff_factor ** attempt``
        seconds, or longer when arXiv's ``Retry-After`` header asks for it, up
        to ``max_retry_after`` seconds. Each retry is logged with its wait.

        Raises:
            ValueError: ``max_retries`` is less than 1, which would fail every
                request without making a single attempt, or
                ``max_retry_after`` is negative.
        """
        if max_retries < 1:
            raise ValueError("max_retries must be a positive integer")
        if max_retry_after < 0:
            raise ValueError("max_retry_after must not be negative")
        self._max_retry_after = max_retry_after
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

        Redirects are followed, so a moved endpoint is not mistaken for a
        failure regardless of how the injected client was configured.

        Raises:
            UpstreamError: Every attempt failed. A transport fault is never
                reported as an empty result.
            ExtractionError: arXiv rejected the request with a status that
                retrying cannot fix, such as ``400`` for a malformed query.
        """
        params: dict[str, str | int] = {
            "search_query": query,
            "start": start_index,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        await self._sleep(self._sleep_before_search)

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            retry_after: float | None = None
            try:
                response = await self._client.get(self.API_URL, params=params, follow_redirects=True)
            except httpx.RequestError as exc:
                last_error = exc
            else:
                if _SUCCESS_FLOOR <= response.status_code < _SUCCESS_CEILING:
                    return response.content
                if not self._is_retryable(response.status_code):
                    raise ExtractionError(
                        f"arXiv rejected the listing request with status {response.status_code}"
                    )
                last_error = UpstreamError(f"arXiv returned status {response.status_code}")
                retry_after = retry_after_from_headers(response.headers)
            if attempt < self._max_retries - 1:
                await self._wait_before_retry("arXiv search", attempt, last_error, retry_after)

        message = f"arXiv search failed after {self._max_retries} attempts"
        self._log(f"{message}: {last_error!r}")
        raise UpstreamError(message) from last_error

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse an Atom listing, treating an unreadable payload as an error.

        An entry without an ``<id>`` cannot be tracked as processed, so it is
        skipped; it still counts toward the page total so paging advances.

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
            if not record_id or record_id in seen_ids:
                continue
            base_id = self._strip_version(record_id)
            if base_id in seen_base_ids:
                continue
            seen_base_ids.add(base_id)
            records.append(
                RawRecord(
                    record_id=record_id,
                    title=entry.title.get_text(strip=True) if entry.title else "",
                    abstract=entry.summary.get_text(strip=True) if entry.summary else "",
                    source_url=self._landing_page_url(entry),
                )
            )
        return records, len(entries)

    @staticmethod
    def _landing_page_url(entry: Any) -> str | None:
        """Return the entry's landing-page link.

        arXiv marks it ``rel="alternate"`` and ``type="text/html"``. Its href
        points at ``/abs/``, so it has to be found by those attributes rather
        than by the text of the URL.
        """
        for link in entry.find_all("link"):
            href = link.get("href")
            if href and (link.get("rel") == "alternate" or link.get("type") == "text/html"):
                return href
        return None

    @staticmethod
    def _is_retryable(status_code: int) -> bool:
        """Whether a status code warrants another attempt.

        Throttling and server-side faults are transient; every other 4xx is a
        permanent verdict about this URL and must not be retried.
        """
        return status_code in _RETRYABLE_STATUS or status_code >= _SERVER_ERROR_FLOOR

    async def _wait_before_retry(
        self, action: str, attempt: int, error: Exception | None, retry_after: float | None
    ) -> None:
        delay = retry_delay(attempt, self._backoff_factor, retry_after, self._max_retry_after)
        self._log(f"{action} attempt {attempt + 1} failed ({error!r}); retrying in {delay:g} s")
        await self._sleep(delay)

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

        The LaTeX source is tried first, then the PDF. A source that is
        permanently unavailable (such as a ``404``) or whose payload its parser
        cannot read (such as a PDF-only submission served as the e-print) is
        passed over for the next one. The abstract is used only when no source
        yields text and none failed transiently. A transport failure is raised
        instead, so the record stays unmarked and is retried on the next run.

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
        return await self._parse(self._latex_parser, content, label="LaTeX", record_id=arxiv_id)

    async def _fetch_pdf_text(self, arxiv_id: str) -> str | None:
        content = await self._get_bytes(
            f"https://arxiv.org/pdf/{arxiv_id}.pdf", label="PDF", record_id=arxiv_id
        )
        if content is None:
            return None
        return await self._parse(self._pdf_parser, content, label="PDF", record_id=arxiv_id)

    async def _parse(self, parser: Parser, content: bytes, label: str, record_id: str) -> str | None:
        """Parse a fetched artifact, treating an unreadable one as unavailable."""
        try:
            text = await asyncio.to_thread(parser.extract_text, content)
        except ParsingError as exc:
            self._log(f"{label} unusable for {record_id!r}: {exc}")
            return None
        return text or None

    async def _get_bytes(self, url: str, label: str, record_id: str) -> bytes | None:
        """Fetch a binary artifact, following redirects and retrying only transient faults.

        Returns:
            The payload, or ``None`` when the source gave a fatal verdict such
            as ``404``, meaning the artifact will never exist at this URL.

        Raises:
            UpstreamError: Every retryable attempt was exhausted.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            retry_after: float | None = None
            try:
                response = await self._client.get(url, follow_redirects=True)
            except httpx.RequestError as exc:
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
                retry_after = retry_after_from_headers(response.headers)
            if attempt < self._max_retries - 1:
                await self._wait_before_retry(f"{label} fetch for {record_id!r}", attempt, last_error, retry_after)

        message = f"{label} fetch failed for {record_id!r} after {self._max_retries} attempts"
        self._log(f"{message}: {last_error!r}")
        raise UpstreamError(message) from last_error
