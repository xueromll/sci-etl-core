from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Iterable

from sci_etl_core.exceptions import (
    EmbeddingError,
    EmbeddingStoreError,
    MalformedResponseError,
    PipelineAborted,
    UpstreamError,
)
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import RawRecord
from sci_etl_core.state.async_base import AsyncStateManager

if TYPE_CHECKING:
    from sci_etl_core.embeddings.ingest_async import AsyncChunkIngestor


class AsyncETLPipeline:
    def __init__(
        self,
        extractor: AsyncExtractor,
        relevance_filter: AsyncRelevanceFilter,
        entity_extractor: AsyncEntityExtractor,
        exporter: AsyncExporter,
        state_manager: AsyncStateManager,
        destination: str,
        max_concurrency: int = 6,
        logger: Callable[[str], None] | None = None,
        sleep: Any = asyncio.sleep,
        closeables: Iterable[Any] | None = None,
        memory_ingestor: "AsyncChunkIngestor | None" = None,
    ) -> None:
        self._extractor = extractor
        self._relevance_filter = relevance_filter
        self._entity_extractor = entity_extractor
        self._exporter = exporter
        self._state_manager = state_manager
        self._destination = destination
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._log = logger or (lambda _msg: None)
        self._sleep = sleep
        self._closeables = list(closeables or [])
        self._memory_ingestor = memory_ingestor

    @property
    def closeables(self) -> list[Any]:
        """Resources whose ``aclose`` the owning facade should await on teardown."""
        return self._closeables

    def log(self, message: str) -> None:
        """Emit a message through the injected logger."""
        self._log(message)

    async def __aenter__(self) -> "AsyncETLPipeline":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        for resource in self._closeables:
            aclose = getattr(resource, "aclose", None)
            if aclose is not None:
                await aclose()
        return False

    async def run(
        self,
        query: str,
        page_size: int | None = None,
        sleep_between: float = 0.0,
        total_limit: int | None = None,
        max_records: int | None = None,
        start_index: int | None = None,
    ) -> int:
        """Process listings until the ceiling is reached or the source is exhausted.

        Paging resumes from the offset saved by the state manager unless
        ``start_index`` is given. Pass ``0`` to rescan a listing whose order has
        shifted since the last run, such as a newest-first feed that gained new
        submissions: processed records are skipped by id, so a rescan costs
        listing requests but never reprocesses a record.

        The only clean exit is an empty listing. A page made up entirely of
        already-processed records is not the end of the data, so paging moves
        past it. Any other interruption raises :class:`PipelineAborted`
        carrying the count processed so far, so a transport fault can never be
        mistaken for end-of-data.

        Raises:
            ValueError: ``start_index`` is negative.
        """
        if start_index is not None and start_index < 0:
            raise ValueError("start_index must not be negative")
        page_size, total_limit = self._resolve_limits(page_size, total_limit, max_records)
        processed_ids = await self._state_manager.load_processed_ids()
        metadata = await self._state_manager.load_metadata()
        if start_index is None:
            start_index = metadata.last_start_index
        total_processed = 0

        while total_processed < total_limit:
            raw_listing = await self._fetch_listing(query, page_size, start_index, total_processed)
            records, total_in_listing = self._parse_listing(raw_listing, processed_ids, total_processed)
            if total_in_listing == 0:
                break

            if records:
                total_processed += await self._process_page(records, processed_ids)

            start_index += total_in_listing
            metadata.last_start_index = start_index
            await self._state_manager.save_metadata(metadata)
            await self._sleep(sleep_between)

        return total_processed

    async def _fetch_listing(
        self, query: str, page_size: int, start_index: int, partial_count: int
    ) -> bytes:
        try:
            raw_listing = await self._extractor.search(query, page_size, start_index)
        except UpstreamError as exc:
            raise PipelineAborted("Listing fetch failed upstream", partial_count) from exc
        if not raw_listing:
            raise PipelineAborted("Listing fetch returned no payload", partial_count)
        return raw_listing

    def _parse_listing(
        self, raw_listing: bytes, processed_ids: set[str], partial_count: int
    ) -> tuple[list[RawRecord], int]:
        try:
            return self._extractor.parse_listing(raw_listing, processed_ids)
        except MalformedResponseError as exc:
            raise PipelineAborted("Listing payload was malformed", partial_count) from exc

    async def _process_page(self, records: list[RawRecord], processed_ids: set[str]) -> int:
        results = await asyncio.gather(
            *(self._process_record(record, processed_ids) for record in records),
            return_exceptions=True,
        )
        processed = 0
        for result in results:
            if isinstance(result, Exception):
                self._log(f"Record processing failed: {result!r}")
            elif result:
                processed += 1
        return processed

    @staticmethod
    def _resolve_limits(
        page_size: int | None, total_limit: int | None, max_records: int | None
    ) -> tuple[int, int]:
        """Resolve the per-request page size and the overall processing ceiling.

        ``max_records`` is a backward-compatible alias: when supplied it seeds
        both the page size and the total limit, matching the historic behavior
        where a single value served both roles.
        """
        if page_size is None:
            page_size = max_records if max_records is not None else 100
        if total_limit is None:
            total_limit = max_records if max_records is not None else page_size
        return page_size, total_limit

    async def _process_record(self, record: RawRecord, processed_ids: set[str]) -> bool:
        async with self._semaphore:
            if not await self._relevance_filter.is_relevant(record):
                await self._mark_done(record, processed_ids)
                return False

            text = await self._extractor.fetch_full_text(record)
            await self._ingest_memory(record, text)
            entities = await self._entity_extractor.extract(text)
            if entities:
                await self._exporter.export(entities, self._destination)

            await self._mark_done(record, processed_ids)
            return True

    async def _ingest_memory(self, record: RawRecord, text: str) -> None:
        """Chunk and store the full text; a memory fault is logged, not fatal.

        The record has already earned its place through the relevance gate, so a
        storage or embedding hiccup must not discard its entity export. The
        failure is surfaced through the logger rather than swallowed silently.
        """
        if self._memory_ingestor is None:
            return
        try:
            await self._memory_ingestor.ingest(record, text)
        except asyncio.CancelledError:
            raise
        except (EmbeddingError, EmbeddingStoreError) as exc:
            self._log(f"Memory ingest failed for {record.record_id}: {exc!r}")

    async def _mark_done(self, record: RawRecord, processed_ids: set[str]) -> None:
        if not record.record_id:
            return
        await self._state_manager.mark_processed(record.record_id)
        processed_ids.add(record.record_id)
