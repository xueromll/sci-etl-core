from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Iterable, NoReturn

from sci_etl_core.exceptions import (
    EmbeddingError,
    EmbeddingStoreError,
    ExtractionError,
    MalformedResponseError,
    PipelineAborted,
)
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import RawRecord
from sci_etl_core.state.async_base import AsyncStateManager

if TYPE_CHECKING:
    from sci_etl_core.embeddings.ingest_async import AsyncChunkIngestor

_STALLED_PAGES_BEFORE_ABORT = 2
_STALL_MESSAGE = "Records kept failing and none could be processed"


class _Outcome(Enum):
    PROCESSED = "processed"
    IRRELEVANT = "irrelevant"
    DEFERRED = "deferred"


class _PageBudget:
    """Relevant-record slots a page may still fill under the run's ceiling."""

    def __init__(self, remaining: int) -> None:
        self._remaining = remaining

    @property
    def exhausted(self) -> bool:
        return self._remaining <= 0

    def reserve(self) -> bool:
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True

    def release(self) -> None:
        self._remaining += 1


@dataclass(slots=True)
class _PageResult:
    processed: int = 0
    deferred: int = 0
    failures: list[BaseException] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failures and not self.deferred

    @property
    def stalled(self) -> bool:
        return bool(self.failures) and self.processed == 0


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
        """Wire the pipeline's collaborators together.

        Raises:
            ValueError: ``max_concurrency`` is less than 1. A zero-permit
                semaphore would leave every record waiting forever.
        """
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
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

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Close every resource, even when an earlier one fails to close.

        A close failure is logged. It is raised only when the block itself
        succeeded, so teardown never masks the exception that ended the block.
        """
        errors: list[Exception] = []
        for resource in self._closeables:
            aclose = getattr(resource, "aclose", None)
            if aclose is None:
                continue
            try:
                await aclose()
            except Exception as error:
                self._log(f"Resource close failed: {error!r}")
                errors.append(error)
        if errors and exc is None:
            raise errors[0]

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

        The saved offset only moves past pages whose every record was settled.
        Once a record fails, or is deferred because ``total_limit`` was reached,
        the offset stays at the start of that page for the rest of the run, so
        the next run revisits the unsettled record instead of skipping it.
        ``total_limit`` is exact: no more relevant records are processed than
        it allows. Records whose ``record_id`` is missing or blank cannot be
        tracked and are skipped with a log message. ``sleep_between`` is waited
        between pages, never after the page that reaches ``total_limit``.

        The only clean exits are an empty listing and reaching ``total_limit``.
        A page made up entirely of already-processed records is not the end of
        the data, so paging moves past it. Any other interruption raises
        :class:`PipelineAborted` carrying the count processed so far, so a
        transport fault can never be mistaken for end-of-data.

        A page on which records failed and none was processed is a stall. A
        single stall is tolerated, because one transient fault on a page of
        mostly irrelevant records says nothing about the source, and a later
        page that processes a record clears it.

        Raises:
            ValueError: ``start_index`` or ``total_limit`` is negative, or the
                resolved ``page_size`` is less than 1.
            PipelineAborted: A listing could not be fetched or parsed, or
                records kept failing with none processed: on a second page
                before any progress, or on the last page before the listing
                ended. That signals a systemic fault, such as a rejected API key
                or an unwritable export, rather than one bad record, so the run
                stops instead of spending calls on every remaining page.
        """
        if start_index is not None and start_index < 0:
            raise ValueError("start_index must not be negative")
        page_size, total_limit = self._resolve_limits(page_size, total_limit, max_records)
        if page_size < 1:
            raise ValueError("page_size must be a positive integer")
        if total_limit < 0:
            raise ValueError("total_limit must not be negative")
        processed_ids = await self._state_manager.load_processed_ids()
        metadata = await self._state_manager.load_metadata()
        if start_index is None:
            start_index = metadata.last_start_index
        total_processed = 0
        offset_settled = True
        stalled_pages = 0
        last_failure: BaseException | None = None

        while total_processed < total_limit:
            raw_listing = await self._fetch_listing(query, page_size, start_index, total_processed)
            records, total_in_listing = self._parse_listing(raw_listing, processed_ids, total_processed)
            if total_in_listing == 0:
                break

            page = await self._process_page(records, processed_ids, total_limit - total_processed)
            total_processed += page.processed
            if page.processed:
                stalled_pages = 0
            elif page.stalled:
                stalled_pages += 1
                last_failure = page.failures[-1]
                if stalled_pages >= _STALLED_PAGES_BEFORE_ABORT:
                    self._abort_stalled(total_processed, last_failure)

            start_index += total_in_listing
            offset_settled = offset_settled and page.complete
            if offset_settled:
                metadata.last_start_index = start_index
            await self._state_manager.save_metadata(metadata)
            if total_processed < total_limit:
                await self._sleep(sleep_between)

        if stalled_pages:
            self._abort_stalled(total_processed, last_failure)
        return total_processed

    @staticmethod
    def _abort_stalled(partial_count: int, cause: BaseException | None) -> NoReturn:
        raise PipelineAborted(_STALL_MESSAGE, partial_count) from cause

    async def _fetch_listing(
        self, query: str, page_size: int, start_index: int, partial_count: int
    ) -> bytes:
        try:
            raw_listing = await self._extractor.search(query, page_size, start_index)
        except ExtractionError as exc:
            raise PipelineAborted("Listing fetch failed", partial_count) from exc
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

    async def _process_page(
        self, records: list[RawRecord], processed_ids: set[str], remaining: int
    ) -> _PageResult:
        trackable: list[RawRecord] = []
        for record in records:
            if record.record_id and record.record_id.strip():
                trackable.append(record)
            else:
                self._log(f"Record skipped: no record_id to track it by (title {record.title!r})")

        budget = _PageBudget(remaining)
        results = await asyncio.gather(
            *(self._process_record(record, processed_ids, budget) for record in trackable),
            return_exceptions=True,
        )
        page = _PageResult()
        for result in results:
            if isinstance(result, BaseException):
                self._log(f"Record processing failed: {result!r}")
                page.failures.append(result)
            elif result is _Outcome.DEFERRED:
                page.deferred += 1
            elif result is _Outcome.PROCESSED:
                page.processed += 1
        return page

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

    async def _process_record(
        self, record: RawRecord, processed_ids: set[str], budget: _PageBudget
    ) -> _Outcome:
        async with self._semaphore:
            if budget.exhausted:
                return _Outcome.DEFERRED
            if not await self._relevance_filter.is_relevant(record):
                await self._mark_done(record, processed_ids)
                return _Outcome.IRRELEVANT
            if not budget.reserve():
                return _Outcome.DEFERRED
            try:
                text = await self._extractor.fetch_full_text(record)
                await self._ingest_memory(record, text)
                entities = await self._entity_extractor.extract(text)
                if entities:
                    await self._exporter.export(entities, self._destination)
                await self._mark_done(record, processed_ids)
            except BaseException:
                budget.release()
                raise
            return _Outcome.PROCESSED

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
        await self._state_manager.mark_processed(record.record_id)
        processed_ids.add(record.record_id)
