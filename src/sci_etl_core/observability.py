"""Structured progress events and run metrics for :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline`."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from sci_etl_core.models import TokenUsage

RecordOutcome = Literal["processed", "irrelevant", "deferred", "failed", "skipped"]
RunOutcome = Literal["completed", "aborted", "interrupted", "cancelled", "failed"]


@dataclass(slots=True)
class RunMetrics:
    """Counts and timings for one pipeline run.

    ``listed`` counts listing entries across every page fetched, and
    ``processed``, ``irrelevant``, ``deferred``, ``failed``, and ``skipped``
    count records by :data:`RecordOutcome`. ``entities_exported`` counts the
    entities handed to the exporter, and ``memory_faults`` the memory ingest
    faults that were logged without failing their record.
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


@dataclass(frozen=True, slots=True)
class RunStarted:
    """A run began. ``start_index`` is the listing offset of its first request."""

    query: str
    start_index: int
    total_limit: int
    newest_first: bool


@dataclass(frozen=True, slots=True)
class PageFetched:
    """A listing page arrived with ``entries`` entries, ``new_records`` of them not yet processed."""

    offset: int
    entries: int
    new_records: int


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class PageFinished:
    """Every record of the page at ``offset`` finished; ``metrics`` is the run so far."""

    offset: int
    duration_seconds: float
    metrics: RunMetrics = field(default_factory=RunMetrics)


@dataclass(frozen=True, slots=True)
class RunFinished:
    """The run ended, however it ended; ``metrics.outcome`` says how."""

    metrics: RunMetrics


PipelineEvent = RunStarted | PageFetched | RecordFinished | PageFinished | RunFinished
