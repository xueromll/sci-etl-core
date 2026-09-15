from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class RawRecord:
    """One article as a listing describes it, before its full text is fetched.

    ``record_id`` is the id state managers track; the pipeline skips a record
    whose id is blank. ``metadata`` holds whatever else the extractor knows, as
    JSON-friendly values: :class:`~sci_etl_core.extractors.arxiv_async.AsyncArxivExtractor`
    fills ``categories``, ``authors``, ``published``, and ``year``.
    :class:`~sci_etl_core.search.index_async.AsyncSearchIndexer` copies it into
    the text index, where the string and integer values under a store's facet
    keys become filterable tags. The chunks
    :class:`~sci_etl_core.embeddings.ingest_async.AsyncChunkIngestor` stores do
    not carry it.
    """

    record_id: str
    title: str
    abstract: str
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TokenUsage:
    """Tokens an API reported across a client's completed requests."""

    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """The prompt and completion tokens together."""
        return self.prompt_tokens + self.completion_tokens

    def record(self, usage: Any) -> None:
        """Add one response's ``usage`` object and count the request.

        A provider that omits usage, or reports a field that is not a
        non-negative integer, contributes zero for that field.
        """
        self.requests += 1
        self.prompt_tokens += _token_count(usage, "prompt_tokens")
        self.completion_tokens += _token_count(usage, "completion_tokens")


def _token_count(usage: Any, field_name: str) -> int:
    value = getattr(usage, field_name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


@dataclass(slots=True)
class PipelineMetadata:
    """What a state manager keeps about the listing between runs.

    ``last_start_index`` is the listing offset the next run resumes from, and
    ``last_run_at`` is the time :meth:`touch` last stamped, or ``None``.
    """

    last_run_at: str | None = None
    last_start_index: int = 0

    def touch(self) -> None:
        """Stamp the current time as an ISO 8601 string with a UTC offset."""
        self.last_run_at = datetime.now(timezone.utc).isoformat()
