"""Structured progress events and run metrics for :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline`."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from sci_etl_core.models import TokenUsage

RecordOutcome = Literal["processed", "irrelevant", "deferred", "failed", "skipped"]
RunOutcome = Literal["completed", "aborted", "interrupted", "cancelled", "failed"]


@dataclass(slots=True, kw_only=True)
class RunMetrics:
    """Counts and timings for one pipeline run.

    ``listed`` counts listing entries across every page fetched, and
    ``processed``, ``irrelevant``, ``deferred``, ``failed``, and ``skipped``
    count records by :data:`RecordOutcome`. ``entities_exported`` counts the
    entities handed to the exporter, and ``memory_faults`` the memory ingest
    faults that were logged without failing their record. ``quarantined``
    counts listed records skipped because they failed ``max_attempts`` times,
    and ``listing_truncated`` is ``True`` when the source stopped the listing
    at its result cap.
    ``duration_seconds`` is measured on a monotonic clock. ``token_usage`` is
    what the pipeline's ``usage_sources`` used during the run, or ``None``
    when it has none. ``outcome`` is ``None`` while the run is in progress.
    """

    pages: int = 0
    listed: int = 0
    processed: int = 0
    irrelevant: int = 0
    deferred: int = 0
    failed: int = 0
    skipped: int = 0
    entities_exported: int = 0
    memory_faults: int = 0
    quarantined: int = 0
    listing_truncated: bool = False
    duration_seconds: float = 0.0
    token_usage: TokenUsage | None = None
    outcome: RunOutcome | None = None

    def count(self, outcome: RecordOutcome) -> None:
        """Add one record to the counter for ``outcome``."""
        setattr(self, outcome, getattr(self, outcome) + 1)

    def snapshot(self) -> RunMetrics:
        """Return a copy that later updates to this object do not change."""
        usage = None if self.token_usage is None else replace(self.token_usage)
        return replace(self, token_usage=usage)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunStarted:
    """A run began.

    ``cursor`` is the listing cursor of its first request, ``None`` for the
    first page. ``start_index`` is the same position as a listing offset when
    the extractor pages by offset, and ``None`` otherwise.
    """

    query: str
    start_index: int | None
    total_limit: int
    newest_first: bool
    cursor: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PageFetched:
    """A listing page arrived with ``entries`` entries, ``new_records`` of them not yet processed.

    ``cursor`` is the cursor the page was requested with, ``None`` for the
    first page, and ``offset`` its listing offset when the extractor pages by
    offset, or ``None``. ``truncated`` is ``True`` when the source stopped the
    listing at its result cap on this page.
    """

    offset: int | None
    entries: int
    new_records: int
    cursor: str | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordFinished:
    """A record left the pipeline for this run.

    ``entities`` is how many entities were exported for it, and ``error`` is
    what failed it when ``outcome`` is ``"failed"``. A ``"skipped"`` record had
    no ``record_id`` to track it by. ``duration_seconds`` counts from the moment
    the record got a concurrency slot, and is 0 for a skipped record.
    """

    record_id: str
    title: str
    outcome: RecordOutcome
    duration_seconds: float
    entities: int = 0
    error: BaseException | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PageFinished:
    """Every record of a page finished; ``metrics`` is the run so far.

    ``cursor`` and ``offset`` locate the page as in :class:`PageFetched`.
    """

    offset: int | None
    duration_seconds: float
    metrics: RunMetrics = field(default_factory=RunMetrics)
    cursor: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunFinished:
    """The run ended, however it ended; ``metrics.outcome`` says how."""

    metrics: RunMetrics


PipelineEvent = RunStarted | PageFetched | RecordFinished | PageFinished | RunFinished
