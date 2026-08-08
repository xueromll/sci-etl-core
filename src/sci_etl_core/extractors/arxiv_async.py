from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx
from bs4 import BeautifulSoup

from sci_etl_core.exceptions import ExtractionError
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.reference_trimmer import trim_after_references

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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

    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
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
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = ExtractionError(f"arXiv returned status {response.status_code}")
                    await self._sleep(self._backoff_factor ** attempt)
                    continue
                response.raise_for_status()
                return response.content
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    await self._sleep(self._backoff_factor ** attempt)
        self._log(f"arXiv search failed after {self._max_retries} attempts: {last_error}")
        return None

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        soup = BeautifulSoup(raw_listing, "xml")
        entries = soup.find_all("entry")
        if not entries:
            return [], 0

        records: list[RawRecord] = []
        for entry in entries:
            raw_id = entry.id.get_text(strip=True) if entry.id else ""
            record_id = self._normalize_id(raw_id)
            if record_id in seen_ids:
                continue
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

    def _normalize_id(self, raw_id: str) -> str:
        """Strip arXiv ``/abs/`` and ``/pdf/`` URL prefixes from a raw record id."""
        if "/abs/" in raw_id:
            return raw_id.split("/abs/")[-1]
        if "/pdf/" in raw_id:
            return raw_id.split("/pdf/")[-1].replace(".pdf", "")
        return raw_id

    async def fetch_full_text(self, record: RawRecord) -> str:
        if not record.record_id:
            return record.abstract

        text = await self._fetch_latex_source(record.record_id)
        if text:
            return trim_after_references(text) or text

        text = await self._fetch_pdf_text(record.record_id)
        if text:
            return trim_after_references(text) or text

        return record.abstract

    async def _fetch_latex_source(self, arxiv_id: str) -> str | None:
        content = await self._get_bytes(f"https://arxiv.org/e-print/{arxiv_id}", label="LaTeX", record_id=arxiv_id)
        if content is None:
            return None
        return (await asyncio.to_thread(self._latex_parser.extract_text, content)) or None

    async def _fetch_pdf_text(self, arxiv_id: str) -> str | None:
        content = await self._get_bytes(f"https://arxiv.org/pdf/{arxiv_id}.pdf", label="PDF", record_id=arxiv_id)
        if content is None:
            return None
        return (await asyncio.to_thread(self._pdf_parser.extract_text, content)) or None

    async def _get_bytes(self, url: str, label: str, record_id: str) -> bytes | None:
        try:
            response = await self._client.get(url)
            if response.status_code != 200:
                return None
            return response.content
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self._log(f"{label} fetch failed for {record_id}: {exc}")
            return None
