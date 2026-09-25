from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, NoReturn

from sci_etl_core._deprecation import warn_advance_notice, warn_logger_argument
from sci_etl_core._listing_position import CursorPosition, NewestFirstPosition, listing_ends
from sci_etl_core._protocols import SupportsAclose, UsageReporter
from sci_etl_core.exceptions import (
    ExtractionError,
    MalformedResponseError,
    PipelineAborted,
    PipelineInterrupted,
    StaleCursorError,
)
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor, OffsetListing
from sci_etl_core.ingest_protocol import MEMORY_FAULTS, MemoryIngestor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import ListingPage, PipelineMetadata, RawRecord, TokenUsage
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
_STALE_AGAIN_MESSAGE = "The source rejected the listing cursor again after the listing restarted"
_DEFAULT_PAGE_SIZE = 100
_STOPPED = object()

Position = CursorPosition | NewestFirstPosition


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
    failed: list[tuple[RawRecord, BaseException]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failed and not self.deferred

    @property
    def stalled(self) -> bool:
        return bool(self.failed) and self.processed == 0


class _Quarantine:
    """Records skipped at listing time because they failed ``max_attempts`` times in earlier runs."""

    def __init__(self, attempts: dict[str, int], max_attempts: int | None) -> None:
        self._attempts = {} if max_attempts is None else {
            record_id: count for record_id, count in attempts.items() if count >= max_attempts
        }
        self._reported: set[str] = set()

    def holds(self, record_id: str) -> bool:
        return record_id in self._attempts

    def report(self, record_id: str) -> str | None:
        """Return the log line for ``record_id`` the first time it is skipped in this run."""
        if record_id in self._reported:
            return None
        self._reported.add(record_id)
        return f"Record {record_id} skipped: quarantined after {self._attempts[record_id]} failed attempts"


class AsyncETLPipeline:
    """Take listed records through relevance, full text, memory, entity extraction, and export.

    Records on a page run concurrently, up to ``max_concurrency`` at a time. An
    irrelevant record is marked processed at once. A relevant one has its full
    text fetched and stored through the optional ``memory_ingestor``, its
    entities extracted and exported, and only then is marked processed, so a
    record that fails is retried on the next run. :meth:`run` describes paging,
    limits, failures, and aborts.
    """

    def __init__(
        self,
        extractor: AsyncExtractor,
        relevance_filter: AsyncRelevanceFilter,
        entity_extractor: AsyncEntityExtractor,
        exporter: AsyncExporter,
        state_manager: AsyncStateManager,
        *,
        destination: str | None = None,
        max_concurrency: int = 6,
        logger: Callable[[str], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        closeables: Iterable[SupportsAclose] = (),
        memory_ingestor: MemoryIngestor | None = None,
        shutdown: ShutdownSignal | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
        usage_sources: Iterable[UsageReporter] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Wire the pipeline's collaborators together.

        The five collaborators are positional; every other argument is
        keyword-only.

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

        ``destination`` is passed to the exporter's ``export`` with each
        record's entities.

        .. deprecated:: 0.5.0
            ``destination`` and ``logger`` emit a :class:`PendingDeprecationWarning`.
            In 0.6.0 exporters take their destination when constructed, and
            the pipeline logs through the standard :mod:`logging` module.

        Raises:
            ValueError: ``max_concurrency`` is less than 1. A zero-permit
                semaphore would leave every record waiting forever.
        """
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        if destination is not None:
            warn_advance_notice(
                "AsyncETLPipeline(destination=)",
                "sci-etl-core 0.6.0 exporters take their destination when they are constructed",
            )
        warn_logger_argument("AsyncETLPipeline", logger)
        self._extractor = extractor
        self._relevance_filter = relevance_filter
        self._entity_extractor = entity_extractor
        self._exporter = exporter
        self._state_manager = state_manager
        self._destination = destination or ""
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._log = logger or (lambda _msg: None)
        self._sleep = sleep
        self._closeables = list(closeables)
        self._memory_ingestor = memory_ingestor
        self._shutdown = shutdown
        self._on_event = on_event
        self._usage_sources = list(usage_sources)
        self._clock = clock
        self._metrics = RunMetrics()
        self._last_run_metrics: RunMetrics | None = None

    @classmethod
    def from_config(
        cls,
        pipeline: PipelineConfig,
        extractor: AsyncExtractor,
        relevance_filter: AsyncRelevanceFilter,
        entity_extractor: AsyncEntityExtractor,
        exporter: AsyncExporter,
        state_manager: AsyncStateManager,
        *,
        destination: str | None = None,
        max_concurrency: int | None = None,
        logger: Callable[[str], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        closeables: Iterable[SupportsAclose] = (),
        memory_ingestor: MemoryIngestor | None = None,
        shutdown: ShutdownSignal | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
        usage_sources: Iterable[UsageReporter] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> AsyncETLPipeline:
        """Build a pipeline whose ``max_concurrency`` comes from the ``pipeline`` config section.

        The other arguments are the constructor's; ``max_concurrency``
        overrides the section's value when given. Pass the section's
        :meth:`~sci_etl_core.config.PipelineConfig.run_arguments` to
        :meth:`run`.
        """
        return cls(
            extractor,
            relevance_filter,
            entity_extractor,
            exporter,
            state_manager,
            destination=destination,
            max_concurrency=pipeline.max_concurrency if max_concurrency is None else max_concurrency,
            logger=logger,
            sleep=sleep,
            closeables=closeables,
            memory_ingestor=memory_ingestor,
            shutdown=shutdown,
            on_event=on_event,
            usage_sources=usage_sources,
            clock=clock,
        )

    @property
    def last_run_metrics(self) -> RunMetrics | None:
        """Metrics of the most recent run, however it ended, or ``None`` before the first run."""
        return None if self._last_run_metrics is None else self._last_run_metrics.snapshot()

    @property
    def shutdown(self) -> ShutdownSignal | None:
        """The shutdown signal this pipeline stops on, if any."""
        return self._shutdown

    @property
    def closeables(self) -> list[SupportsAclose]:
        """Resources whose ``aclose`` the owning facade should await on teardown."""
        return self._closeables

    def log(self, message: str) -> None:
        """Emit a message through the injected logger."""
        self._log(message)

    async def __aenter__(self) -> AsyncETLPipeline:
        return self

    async def __aexit__(self, exc_type: object, exc: BaseException | None, tb: object) -> None:
        """Close every resource, even when an earlier one fails to close.

        A resource without ``aclose``, such as an ``AsyncFileStateManager``,
        is skipped. A close failure is logged. It is raised only when the block
        itself succeeded, so teardown never masks the exception that ended the
        block.
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
        *,
        page_size: int = _DEFAULT_PAGE_SIZE,
        sleep_between: float = 0.0,
        total_limit: int | None = None,
        start_index: int | None = None,
        newest_first: bool = False,
        max_attempts: int | None = 3,
    ) -> int:
        """Process listing pages until the ceiling is reached or the listing ends.

        Every argument after ``query`` is keyword-only. ``total_limit``
        defaults to ``page_size``.

        Paging resumes from the cursor saved by the state manager unless
        ``start_index`` is given. Pass ``0`` to rescan a listing from its first
        page: processed records are skipped by id, so a rescan costs listing
        requests but never reprocesses a record. A ``start_index`` above 0
        needs an extractor that pages by offset
        (:class:`~sci_etl_core.extractors.async_base.OffsetListing`).

        Pass ``newest_first=True`` for a listing that puts new submissions
        first, such as arXiv's; it too needs an ``OffsetListing`` extractor.
        The run pages from offset 0 until it reaches the records the previous
        run saw at the top of the listing, then jumps to the saved offset moved
        down by the number of new submissions, less one page to absorb entries
        removed from the listing, so the records in between are not listed
        again. A run without saved head records, such as the first one in this
        mode, rescans from offset 0, as does a run that never finds them. The
        head records are saved through
        :class:`~sci_etl_core.models.PipelineMetadata` next to the cursor.

        The saved cursor only moves past pages whose every record was settled.
        Once a record fails, or is deferred because ``total_limit`` was reached,
        the cursor stays at the start of that page for the rest of the run, so
        the next run revisits the unsettled record instead of skipping it.
        ``total_limit`` is exact: no more relevant records are processed than
        it allows. Records whose ``record_id`` is missing or blank cannot be
        tracked and are skipped with a log message. ``sleep_between`` is waited
        between pages, never after the page that reaches ``total_limit`` or
        ends the listing.

        A page with no next cursor, or with no entries, ends the listing, and
        the run completes. An ``OffsetListing`` extractor then saves the offset
        past the last entry, so entries appended later are found by the next
        run; any other extractor saves no cursor, so the next run starts from
        the first page. A page the source marks ``truncated``, because it
        stopped at its own result cap, completes the run too, reports the cap
        in :attr:`~sci_etl_core.observability.RunMetrics.listing_truncated` and
        one log line, and saves no cursor, so the next run pages the reachable
        results again instead of stopping at the cap.
        :attr:`~sci_etl_core.models.PipelineMetadata.truncated` records it
        until a run reaches the end of the listing without a cap. When the
        source rejects the cursor with
        :class:`~sci_etl_core.exceptions.StaleCursorError`, the run restarts
        the listing from its first page, once per run.

        With ``max_attempts`` set, a record's failed attempts are counted
        through the state manager's ``record_failure``, and a listed record
        whose attempts reached ``max_attempts`` in earlier runs is skipped as
        quarantined: it is not processed, counts as settled, and is counted in
        :attr:`~sci_etl_core.observability.RunMetrics.quarantined`. Failures
        are counted only from pages that processed a record, or from stalled
        pages that a later page of the run cleared, so an outage that fails
        every record never quarantines one. ``max_attempts=None`` counts
        nothing.

        With a ``shutdown`` signal, a shutdown request stops the run cleanly.
        Records already in flight are finished, records not yet started are
        left for the next run, and a pending listing fetch or wait between
        pages is cancelled. The saved cursor does not move past the page that
        was cut short, and :class:`PipelineInterrupted` is raised.

        State is flushed through the state manager's ``flush`` whenever a run
        ends, however it ends. A flush failure after the run itself failed is
        logged, so it never hides the original error.

        A page made up entirely of processed or quarantined records is not the
        end of the data, so paging moves past it. Any other interruption raises
        :class:`PipelineAborted` carrying the count processed so far, so a
        transport fault can never be mistaken for the end of the listing.

        A page on which records failed and none was processed is a stall. A
        single stall is tolerated, because one transient fault on a page of
        mostly irrelevant records says nothing about the source, and a later
        page that processes a record clears it.

        Raises:
            ValueError: ``start_index`` or ``total_limit`` is negative,
                ``page_size`` or ``max_attempts`` is less than 1,
                ``start_index`` is given with ``newest_first``, or
                ``newest_first`` or a ``start_index`` above 0 is used with an
                extractor that is not an ``OffsetListing``. Raised before any
                request.
            PipelineAborted: A listing page could not be fetched or parsed, the
                source rejected the cursor again after a restart, or records
                kept failing with none processed: on a second page before any
                progress, or on the last page of the listing. That signals a
                systemic fault, such as a rejected API key or an unwritable
                export, rather than one bad record, so the run stops instead of
                spending calls on every remaining page.
            PipelineInterrupted: A shutdown was requested through ``shutdown``.
                It subclasses :class:`PipelineAborted`.
        """
        offsets = self._extractor if isinstance(self._extractor, OffsetListing) else None
        if start_index is not None and start_index < 0:
            raise ValueError("start_index must not be negative")
        if start_index is not None and newest_first:
            raise ValueError("start_index cannot be combined with newest_first")
        if page_size < 1:
            raise ValueError("page_size must be a positive integer")
        if total_limit is None:
            total_limit = page_size
        if total_limit < 0:
            raise ValueError("total_limit must not be negative")
        if max_attempts is not None and max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer or None")
        if offsets is None and newest_first:
            raise ValueError(f"newest_first needs an OffsetListing extractor; {type(self._extractor).__name__} is not")
        if offsets is None and start_index:
            raise ValueError(f"start_index needs an OffsetListing extractor; {type(self._extractor).__name__} is not")
        self._metrics = RunMetrics()
        started = self._clock()
        usage_before = self._usage_total()
        outcome: RunOutcome = "failed"
        try:
            with self._signal_guard():
                try:
                    processed = await self._run_pages(
                        query, page_size, sleep_between, total_limit, start_index, newest_first, max_attempts
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
        max_attempts: int | None,
    ) -> int:
        processed_ids = await self._state_manager.load_processed_ids()
        attempts = await self._state_manager.failure_counts() if max_attempts is not None else {}
        quarantine = _Quarantine(attempts, max_attempts)
        metadata = await self._state_manager.load_metadata()
        position = self._position(metadata, page_size, start_index, newest_first)
        self._emit(
            RunStarted(
                query=query,
                start_index=position.offset,
                total_limit=total_limit,
                newest_first=newest_first,
                cursor=position.cursor,
            )
        )
        total_processed = 0
        stalled_pages = 0
        last_failure: BaseException | None = None
        held_failures: list[tuple[RawRecord, BaseException]] = []
        restarted = False

        while total_processed < total_limit:
            if self._stop_requested():
                raise PipelineInterrupted(_INTERRUPT_MESSAGE, total_processed)
            cursor, offset = position.cursor, position.offset
            try:
                page = await self._unless_stopped(self._fetch_page(query, cursor, page_size, total_processed))
            except StaleCursorError as exc:
                if restarted:
                    raise PipelineAborted(_STALE_AGAIN_MESSAGE, total_processed) from exc
                restarted = True
                self._log(f"The source no longer accepts cursor {cursor!r}; restarting the listing from its first page")
                position.restart()
                await self._state_manager.save_metadata(metadata)
                continue
            if page is _STOPPED:
                raise PipelineInterrupted(_INTERRUPT_MESSAGE, total_processed)
            records = self._unprocessed(page, processed_ids, quarantine)
            self._metrics.pages += 1
            self._metrics.listed += page.entries
            self._emit(
                PageFetched(
                    offset=offset,
                    entries=page.entries,
                    new_records=len(records),
                    cursor=cursor,
                    truncated=page.truncated,
                )
            )
            if page.truncated and not self._metrics.listing_truncated:
                self._metrics.listing_truncated = True
                self._log("The source stopped the listing at its result cap; the next run starts from the first page")

            result = _PageResult()
            if page.entries:
                page_started = self._clock()
                result = await self._process_page(records, processed_ids, total_limit - total_processed)
                self._emit(
                    PageFinished(
                        offset=offset,
                        duration_seconds=self._clock() - page_started,
                        metrics=self._metrics.snapshot(),
                        cursor=cursor,
                    )
                )
                total_processed += result.processed
                if result.processed:
                    stalled_pages = 0
                    await self._commit_failures([*held_failures, *result.failed], max_attempts)
                    held_failures.clear()
                elif result.stalled:
                    stalled_pages += 1
                    last_failure = result.failed[-1][1]
                    held_failures.extend(result.failed)
                    if stalled_pages >= _STALLED_PAGES_BEFORE_ABORT:
                        self._abort_stalled(total_processed, last_failure)
            if listing_ends(page) and stalled_pages:
                self._abort_stalled(total_processed, last_failure)

            if page.truncated:
                position.truncate()
                await self._state_manager.save_metadata(metadata)
                break
            more = position.advance(page, result.complete)
            await self._state_manager.save_metadata(metadata)
            if not more:
                break
            if total_processed < total_limit:
                await self._unless_stopped(self._sleep(sleep_between))
        return total_processed

    def _position(
        self, metadata: PipelineMetadata, page_size: int, start_index: int | None, newest_first: bool
    ) -> Position:
        offsets = self._extractor if isinstance(self._extractor, OffsetListing) else None
        if newest_first and offsets is not None:
            return NewestFirstPosition(metadata, page_size, offsets, self._log)
        if start_index is None:
            return CursorPosition(metadata, metadata.cursor, offsets)
        cursor = offsets.cursor_for_offset(start_index) if offsets is not None and start_index else None
        return CursorPosition(metadata, cursor, offsets)

    def _unprocessed(self, page: ListingPage, processed_ids: set[str], quarantine: _Quarantine) -> list[RawRecord]:
        records: list[RawRecord] = []
        for record in page.records:
            if record.record_id in processed_ids:
                continue
            if quarantine.holds(record.record_id):
                message = quarantine.report(record.record_id)
                if message is not None:
                    self._metrics.quarantined += 1
                    self._log(message)
                continue
            records.append(record)
        return records

    async def _commit_failures(
        self, failures: list[tuple[RawRecord, BaseException]], max_attempts: int | None
    ) -> None:
        if max_attempts is None:
            return
        for record, error in failures:
            attempts = await self._state_manager.record_failure(record.record_id, f"{type(error).__name__}: {error}")
            if attempts >= max_attempts:
                self._log(f"Record {record.record_id} failed {attempts} times; later runs skip it as quarantined")

    def _signal_guard(self) -> AbstractContextManager[Any]:
        if self._shutdown is None:
            return nullcontext()
        return self._shutdown.guard()

    def _stop_requested(self) -> bool:
        return self._shutdown is not None and self._shutdown.triggered

    async def _unless_stopped(self, work: Awaitable[Any]) -> Any:
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
        self._emit(RunFinished(metrics=self._metrics.snapshot()))

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
        self._emit(
            RecordFinished(
                record_id=record.record_id,
                title=record.title,
                outcome=outcome,
                duration_seconds=duration,
                entities=entities,
                error=error,
            )
        )

    async def _flush_after_failure(self) -> None:
        try:
            await self._state_manager.flush()
        except Exception as error:
            self._log(f"State flush failed: {error!r}")

    @staticmethod
    def _abort_stalled(partial_count: int, cause: BaseException | None) -> NoReturn:
        raise PipelineAborted(_STALL_MESSAGE, partial_count) from cause

    async def _fetch_page(self, query: str, cursor: str | None, page_size: int, partial_count: int) -> ListingPage:
        try:
            return await self._extractor.fetch_page(query, cursor, page_size)
        except StaleCursorError:
            raise
        except MalformedResponseError as exc:
            raise PipelineAborted("Listing payload was malformed", partial_count) from exc
        except ExtractionError as exc:
            raise PipelineAborted("Listing fetch failed", partial_count) from exc

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
        for record, result in zip(trackable, results, strict=True):
            if isinstance(result, BaseException):
                self._log(f"Record processing failed: {result!r}")
                page.failed.append((record, result))
            elif result is _Outcome.DEFERRED:
                page.deferred += 1
            elif result is _Outcome.PROCESSED:
                page.processed += 1
        return page

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
