from __future__ import annotations

import asyncio
import time
import warnings
from contextlib import nullcontext
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ContextManager, Coroutine, Iterable, NoReturn

from sci_etl_core._listing_head import NewestFirstCursor
from sci_etl_core.exceptions import (
    ExtractionError,
    MalformedResponseError,
    PipelineAborted,
    PipelineInterrupted,
)
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.ingest_protocol import MEMORY_FAULTS, MemoryIngestor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import RawRecord, TokenUsage
from sci_etl_core.observability import (
    PageFetched,
    PageFinished,
    PipelineEvent,
    RecordFinished,
    RecordOutcome,
    RunFinished,
    RunMetrics,
    RunOutcome,
    RunStarted,
)
from sci_etl_core.signals import ShutdownSignal
from sci_etl_core.state.async_base import AsyncStateManager

if TYPE_CHECKING:
    from sci_etl_core.config import PipelineConfig

_STALLED_PAGES_BEFORE_ABORT = 2
_STALL_MESSAGE = "Records kept failing and none could be processed"
_INTERRUPT_MESSAGE = "Run stopped by a shutdown request"
_STOPPED = object()


class _Outcome(Enum):
    PROCESSED = "processed"
    IRRELEVANT = "irrelevant"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class _Settled:
    outcome: _Outcome
    entities: int = 0


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
    """Take listed records through relevance, full text, memory, entity extraction, and export.

    Records on a page run concurrently, up to ``max_concurrency`` at a time. An
    irrelevant record is marked processed at once. A relevant one has its full
    text fetched and stored through the optional ``memory_ingestor``, its
    entities extracted and exported, and only then is marked processed, so a
    record that fails is retried on the next run. :meth:`run` describes paging,
    limits, and aborts.
    """

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
        memory_ingestor: MemoryIngestor | None = None,
        shutdown: ShutdownSignal | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
        usage_sources: Iterable[Any] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Wire the pipeline's collaborators together.

        ``memory_ingestor`` is any :class:`~sci_etl_core.ingest_protocol.MemoryIngestor`,
        such as an ``AsyncChunkIngestor``, an ``AsyncSearchIndexer``, or an
        ``AsyncCompositeIngestor`` feeding both. An exception it raises that is
        in :data:`~sci_etl_core.ingest_protocol.MEMORY_FAULTS` is logged as
        ``Memory ingest failed for <record_id>: <error>``, and the record's
        entities are still exported. Any other exception, including
        :class:`~sci_etl_core.exceptions.SearchQueryError`, fails the record.

        ``closeables`` are closed each time ``async with pipeline`` exits, and a
        SQLite store reopens when it is used after that. List a store only when
        the pipeline owns it, as in a one-shot script; an application that keeps
        using its stores after a run closes them itself. ``logger`` receives
        every log line, and ``sleep`` is awaited between pages.

        ``shutdown`` makes a run stop cleanly on SIGINT or SIGTERM, or when
        :meth:`~sci_etl_core.signals.ShutdownSignal.request` is called: see
        :meth:`run`. The pipeline installs its handlers for the duration of each
        run, unless an enclosing ``shutdown.guard()`` already has.

        ``on_event`` receives a :mod:`~sci_etl_core.observability` event as the
        run progresses: :class:`~sci_etl_core.observability.RunStarted`,
        :class:`~sci_etl_core.observability.PageFetched`, one
        :class:`~sci_etl_core.observability.RecordFinished` per record,
        :class:`~sci_etl_core.observability.PageFinished`, and
        :class:`~sci_etl_core.observability.RunFinished`. It is called on the
        event loop, so it must not block. An exception it raises is logged as
        ``Event handler failed: <error>`` and does not affect the run.
        ``usage_sources`` are clients with a ``usage`` property, such as the
        LLM client and embedder, whose tokens used during a run are reported in
        :attr:`last_run_metrics`. ``clock`` measures durations.

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
        self._shutdown = shutdown
        self._on_event = on_event
        self._usage_sources = list(usage_sources)
        self._clock = clock
        self._metrics = RunMetrics()
        self._last_run_metrics: RunMetrics | None = None

    @classmethod
    def from_config(cls, pipeline: PipelineConfig, **arguments: Any) -> "AsyncETLPipeline":
        """Build a pipeline whose ``max_concurrency`` comes from the ``pipeline`` config section.

        ``arguments`` are the other constructor arguments, the collaborators
        among them, and may override ``max_concurrency``. Pass the section's
        :meth:`~sci_etl_core.config.PipelineConfig.run_arguments` to
        :meth:`run`.
        """
        arguments.setdefault("max_concurrency", pipeline.max_concurrency)
        return cls(**arguments)

    @property
    def last_run_metrics(self) -> RunMetrics | None:
        """Metrics of the most recent run, however it ended, or ``None`` before the first run."""
        return None if self._last_run_metrics is None else self._last_run_metrics.snapshot()

    @property
    def shutdown(self) -> ShutdownSignal | None:
        """The shutdown signal this pipeline stops on, if any."""
        return self._shutdown

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
        newest_first: bool = False,
    ) -> int:
        """Process listings until the ceiling is reached or the source is exhausted.

        Paging resumes from the offset saved by the state manager unless
        ``start_index`` is given. Pass ``0`` to rescan a listing whose order has
        shifted since the last run: processed records are skipped by id, so a
        rescan costs listing requests but never reprocesses a record.

        Pass ``newest_first=True`` for a listing that puts new submissions
        first, such as arXiv's. The run pages from offset 0 until it reaches
        the records the previous run saw at the top of the listing, then jumps
        to the saved offset moved down by the number of new submissions, less
        one page to absorb entries removed from the listing, so the records in
        between are not listed again. A run without saved head
        records, such as the first one in this mode, rescans from offset 0, as
        does a run that never finds them. The head records are saved through
        :class:`~sci_etl_core.models.PipelineMetadata` next to the offset.

        The saved offset only moves past pages whose every record was settled.
        Once a record fails, or is deferred because ``total_limit`` was reached,
        the offset stays at the start of that page for the rest of the run, so
        the next run revisits the unsettled record instead of skipping it.
        ``total_limit`` is exact: no more relevant records are processed than
        it allows. ``max_records`` is a deprecated alias that sets both
        ``page_size`` and ``total_limit`` when they are not given. Records
        whose ``record_id`` is missing or blank cannot be tracked and are
        skipped with a log message. ``sleep_between`` is waited between pages,
        never after the page that reaches ``total_limit``.

        With a ``shutdown`` signal, a shutdown request stops the run cleanly.
        Records already in flight are finished, records not yet started are
        left for the next run, and a pending listing fetch or wait between
        pages is cancelled. The saved offset does not move past the page that
        was cut short, and :class:`PipelineInterrupted` is raised.

        State is flushed through the state manager's ``flush`` whenever a run
        ends, however it ends. A flush failure after the run itself failed is
        logged, so it never hides the original error.

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
            ValueError: ``start_index`` or ``total_limit`` is negative, the
                resolved ``page_size`` is less than 1, or ``start_index`` is
                given with ``newest_first``.
            PipelineAborted: A listing could not be fetched or parsed, or
                records kept failing with none processed: on a second page
                before any progress, or on the last page before the listing
                ended. That signals a systemic fault, such as a rejected API key
                or an unwritable export, rather than one bad record, so the run
                stops instead of spending calls on every remaining page.
            PipelineInterrupted: A shutdown was requested through ``shutdown``.
                It subclasses :class:`PipelineAborted`.
        """
        if max_records is not None:
            warnings.warn(
                "run(max_records=) is deprecated and will be removed in sci-etl-core 0.5.0; "
                "pass page_size and total_limit",
                DeprecationWarning,
                stacklevel=2,
            )
        if start_index is not None and start_index < 0:
            raise ValueError("start_index must not be negative")
        if start_index is not None and newest_first:
            raise ValueError("start_index cannot be combined with newest_first")
        page_size, total_limit = self._resolve_limits(page_size, total_limit, max_records)
        if page_size < 1:
            raise ValueError("page_size must be a positive integer")
        if total_limit < 0:
            raise ValueError("total_limit must not be negative")
        self._metrics = RunMetrics()
        started = self._clock()
        usage_before = self._usage_total()
        outcome: RunOutcome = "failed"
        try:
            with self._signal_guard():
                try:
                    processed = await self._run_pages(
                        query, page_size, sleep_between, total_limit, start_index, newest_first
                    )
                except BaseException:
                    await self._flush_after_failure()
                    raise
                await self._state_manager.flush()
            outcome = "completed"
            return processed
        except PipelineInterrupted:
            outcome = "interrupted"
            raise
        except PipelineAborted:
            outcome = "aborted"
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            self._finish_metrics(outcome, started, usage_before)

    async def _run_pages(
        self,
        query: str,
        page_size: int,
        sleep_between: float,
        total_limit: int,
        start_index: int | None,
        newest_first: bool,
    ) -> int:
        processed_ids = await self._state_manager.load_processed_ids()
        metadata = await self._state_manager.load_metadata()
        cursor = NewestFirstCursor(metadata, page_size) if newest_first else None
        if cursor is not None:
            start_index = 0
        elif start_index is None:
            start_index = metadata.last_start_index
        self._emit(RunStarted(query, start_index, total_limit, newest_first))
        total_processed = 0
        offset_settled = True
        stalled_pages = 0
        last_failure: BaseException | None = None

        while total_processed < total_limit:
            if self._stop_requested():
                raise PipelineInterrupted(_INTERRUPT_MESSAGE, total_processed)
            raw_listing = await self._unless_stopped(
                self._fetch_listing(query, page_size, start_index, total_processed)
            )
            if raw_listing is _STOPPED:
                raise PipelineInterrupted(_INTERRUPT_MESSAGE, total_processed)
            records, total_in_listing = self._parse_listing(raw_listing, processed_ids, total_processed)
            self._metrics.pages += 1
            self._metrics.listed += total_in_listing
            self._emit(PageFetched(start_index, total_in_listing, len(records)))
            if total_in_listing == 0:
                if cursor is None:
                    break
                was_scanning = cursor.scanning
                resume_at = cursor.listing_ended()
                await self._state_manager.save_metadata(metadata)
                if was_scanning:
                    self._log("Listing ended before the records last seen at its head; rescanned from offset 0")
                if resume_at is None:
                    break
                self._log(f"Records last seen before the saved offset have moved; paging on from {resume_at}")
                start_index = resume_at
                continue

            page_started = self._clock()
            page = await self._process_page(records, processed_ids, total_limit - total_processed)
            self._emit(PageFinished(start_index, self._clock() - page_started, self._metrics.snapshot()))
            total_processed += page.processed
            if page.processed:
                stalled_pages = 0
            elif page.stalled:
                stalled_pages += 1
                last_failure = page.failures[-1]
                if stalled_pages >= _STALLED_PAGES_BEFORE_ABORT:
                    self._abort_stalled(total_processed, last_failure)

            if cursor is not None:
                listed_ids = self._listed_ids(raw_listing, total_processed)
                was_scanning, was_realigned = cursor.scanning, cursor.realigned
                start_index = cursor.observe_page(start_index, listed_ids, total_in_listing, page.complete)
                if was_scanning and not cursor.scanning:
                    self._log(f"{cursor.shift} new listing entries since the last run; resuming at {start_index}")
                if cursor.realigned and not was_realigned:
                    self._log(f"Records last seen before the saved offset have moved; paging on from {start_index}")
            else:
                start_index += total_in_listing
                offset_settled = offset_settled and page.complete
                if offset_settled:
                    metadata.last_start_index = start_index
            await self._state_manager.save_metadata(metadata)
            if total_processed < total_limit:
                await self._unless_stopped(self._sleep(sleep_between))

        if stalled_pages:
            self._abort_stalled(total_processed, last_failure)
        return total_processed

    def _signal_guard(self) -> ContextManager[Any]:
        if self._shutdown is None:
            return nullcontext()
        return self._shutdown.guard()

    def _stop_requested(self) -> bool:
        return self._shutdown is not None and self._shutdown.triggered

    async def _unless_stopped(self, work: Coroutine[Any, Any, Any]) -> Any:
        """Await ``work``, or cancel it and return ``_STOPPED`` once a shutdown is requested.

        Only work that settles no record state is raced this way: a listing
        fetch or the wait between pages.
        """
        if self._shutdown is None:
            return await work
        work_task = asyncio.ensure_future(work)
        stop_task = asyncio.ensure_future(self._shutdown.wait())
        try:
            await asyncio.wait({work_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (work_task, stop_task):
                task.cancel()
            await asyncio.gather(work_task, stop_task, return_exceptions=True)
        if work_task.cancelled():
            return _STOPPED
        return work_task.result()

    def _emit(self, event: PipelineEvent) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception as error:
            self._log(f"Event handler failed: {error!r}")

    def _usage_total(self) -> TokenUsage | None:
        usages = [usage for usage in (source.usage for source in self._usage_sources) if usage is not None]
        if not usages:
            return None
        return sum(usages, TokenUsage())

    def _finish_metrics(self, outcome: RunOutcome, started: float, usage_before: TokenUsage | None) -> None:
        self._metrics.outcome = outcome
        self._metrics.duration_seconds = self._clock() - started
        usage_after = self._usage_total()
        if usage_after is not None:
            self._metrics.token_usage = usage_after - (usage_before or TokenUsage())
        self._last_run_metrics = self._metrics.snapshot()
        self._emit(RunFinished(self._metrics.snapshot()))

    def _record_finished(
        self,
        record: RawRecord,
        outcome: RecordOutcome,
        started: float | None,
        entities: int = 0,
        error: BaseException | None = None,
    ) -> None:
        self._metrics.count(outcome)
        self._metrics.entities_exported += entities
        duration = 0.0 if started is None else self._clock() - started
        self._emit(RecordFinished(record.record_id, record.title, outcome, duration, entities, error))

    async def _flush_after_failure(self) -> None:
        try:
            await self._state_manager.flush()
        except Exception as error:
            self._log(f"State flush failed: {error!r}")

    def _listed_ids(self, raw_listing: bytes, partial_count: int) -> list[str]:
        records, _ = self._parse_listing(raw_listing, set(), partial_count)
        return [record.record_id for record in records if record.record_id]

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
                self._record_finished(record, "skipped", None)

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
            started = self._clock()
            try:
                settled = await self._settle_record(record, processed_ids, budget)
            except BaseException as error:
                self._record_finished(record, "failed", started, error=error)
                raise
            self._record_finished(record, settled.outcome.value, started, settled.entities)
            return settled.outcome

    async def _settle_record(self, record: RawRecord, processed_ids: set[str], budget: _PageBudget) -> _Settled:
        if budget.exhausted or self._stop_requested():
            return _Settled(_Outcome.DEFERRED)
        if not await self._relevance_filter.is_relevant(record):
            await self._mark_done(record, processed_ids)
            return _Settled(_Outcome.IRRELEVANT)
        if not budget.reserve():
            return _Settled(_Outcome.DEFERRED)
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
        return _Settled(_Outcome.PROCESSED, len(entities))

    async def _ingest_memory(self, record: RawRecord, text: str) -> None:
        """Store the full text in memory; a memory fault is logged, not fatal.

        The record has already earned its place through the relevance gate, so a
        storage or embedding hiccup (:data:`~sci_etl_core.ingest_protocol.MEMORY_FAULTS`)
        must not discard its entity export. The failure is surfaced through the
        logger rather than swallowed silently. Any other exception, such as a
        :class:`~sci_etl_core.exceptions.SearchQueryError`, fails the record.
        """
        if self._memory_ingestor is None:
            return
        try:
            await self._memory_ingestor.ingest(record, text)
        except asyncio.CancelledError:
            raise
        except MEMORY_FAULTS as exc:
            self._metrics.memory_faults += 1
            self._log(f"Memory ingest failed for {record.record_id}: {exc!r}")

    async def _mark_done(self, record: RawRecord, processed_ids: set[str]) -> None:
        await self._state_manager.mark_processed(record.record_id)
        processed_ids.add(record.record_id)
