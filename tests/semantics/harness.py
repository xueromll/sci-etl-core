"""In-memory collaborators for the run-semantics tests.

Each fake records what the pipeline asked of it, so a rule's test can assert
on requests, saved cursors, and marked records instead of on mock call lists.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from typing import Any

from sci_etl_core.exceptions import LLMError, MalformedResponseError, StaleCursorError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import ListingPage, PipelineMetadata, RawRecord
from sci_etl_core.observability import PipelineEvent
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.signals import ShutdownSignal
from sci_etl_core.state.async_base import AsyncStateManager


def records(*record_ids: str) -> list[RawRecord]:
    return [RawRecord(record_id=record_id, title=f"title {record_id}", abstract="abstract") for record_id in record_ids]


class Listing(AsyncExtractor):
    """A listing served by offset from a list of records, like arXiv's.

    With ``cap`` set, no entry at or past that offset is served, and the page
    that reaches the cap is ``truncated``, as OpenAlex and PubMed stop at their
    result caps. ``stale`` cursors raise :class:`StaleCursorError`.
    """

    def __init__(self, listed: Iterable[RawRecord]) -> None:
        self.listed = list(listed)
        self.requests: list[int] = []
        self.cursors: list[str | None] = []
        self.fetch_faults: dict[int, BaseException] = {}
        self.malformed_pages: set[int] = set()
        self.stale: set[str | None] = set()
        self.cap: int | None = None
        self.ends_on_last_page = False

    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self.cursors.append(cursor)
        if cursor in self.stale:
            self.stale.discard(cursor)
            raise StaleCursorError(f"cursor {cursor} expired")
        offset = int(cursor or 0)
        self.requests.append(offset)
        if offset in self.fetch_faults:
            raise self.fetch_faults[offset]
        if offset in self.malformed_pages:
            raise MalformedResponseError("unreadable listing")
        end = offset + page_size if self.cap is None else min(offset + page_size, self.cap)
        page = self.listed[offset:end]
        truncated = self.cap is not None and end >= self.cap and len(self.listed) > self.cap
        at_end = self.ends_on_last_page and offset + len(page) >= len(self.listed)
        next_cursor = None if not page or truncated or at_end else str(offset + len(page))
        return ListingPage(records=tuple(page), entries=len(page), next_cursor=next_cursor, truncated=truncated)

    async def fetch_full_text(self, record: RawRecord) -> str:
        return f"text:{record.record_id}"


class OpaqueListing(AsyncExtractor):
    """A listing whose cursors are opaque tokens, like OpenAlex's, ending on the page without a next cursor."""

    def __init__(self, listed: Iterable[RawRecord]) -> None:
        self.listed = list(listed)
        self.cursors: list[str | None] = []
        self.stale: set[str | None] = set()

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self.cursors.append(cursor)
        if cursor in self.stale:
            self.stale.discard(cursor)
            raise StaleCursorError(f"cursor {cursor} expired")
        offset = 0 if cursor is None else int(cursor.removeprefix("token-"))
        page = self.listed[offset : offset + page_size]
        end = offset + len(page)
        next_cursor = f"token-{end}" if end < len(self.listed) else None
        return ListingPage(records=tuple(page), entries=len(page), next_cursor=next_cursor)

    async def fetch_full_text(self, record: RawRecord) -> str:
        return f"text:{record.record_id}"


class Relevance(AsyncRelevanceFilter):
    def __init__(self, irrelevant: Iterable[str] = ()) -> None:
        self.irrelevant = set(irrelevant)
        self.asked: list[str] = []

    async def is_relevant(self, record: RawRecord) -> bool:
        self.asked.append(record.record_id)
        return record.record_id not in self.irrelevant


class Entities(AsyncEntityExtractor):
    """Returns one entity per record, and fails for the record ids in ``failing``."""

    def __init__(self, failing: Iterable[str] = ()) -> None:
        self.failing = set(failing)
        self.extracted: list[str] = []
        self.before_extract: Any = None

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        record_id = str(text).removeprefix("text:")
        if self.before_extract is not None:
            await self.before_extract(record_id)
        if record_id in self.failing:
            raise LLMError(f"extraction failed for {record_id}")
        self.extracted.append(record_id)
        return [{"record": record_id}]


class ScriptedLLM(AsyncLLMClient):
    """Answers each completion with ``answer(user_content)``, which may raise."""

    def __init__(self, answer: Callable[[str], Any]) -> None:
        self.answer = answer
        self.requests: list[str] = []

    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> Any:  # noqa: ASYNC109
        self.requests.append(user_content)
        return self.answer(user_content)


class Exporter(AsyncExporter):
    def __init__(self) -> None:
        self.exported: list[dict[str, Any]] = []

    async def export(self, data: Any, destination: str) -> None:
        self.exported.extend(data)


def copied(metadata: PipelineMetadata) -> PipelineMetadata:
    return dataclasses.replace(metadata, head_ids=list(metadata.head_ids), tail_ids=list(metadata.tail_ids))


class State(AsyncStateManager):
    def __init__(self, processed: Iterable[str] = (), metadata: PipelineMetadata | None = None) -> None:
        self.processed = set(processed)
        self.metadata = metadata or PipelineMetadata()
        self.marked: list[str] = []
        self.saved_cursors: list[str | None] = []
        self.failures: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self.flushes = 0
        self.flush_fault: BaseException | None = None

    async def load_processed_ids(self) -> set[str]:
        return set(self.processed)

    async def mark_processed(self, record_id: str) -> None:
        self.processed.add(record_id)
        self.marked.append(record_id)
        self.failures.pop(record_id, None)

    async def record_failure(self, record_id: str, error: str) -> int:
        self.failures[record_id] = self.failures.get(record_id, 0) + 1
        self.errors[record_id] = error
        return self.failures[record_id]

    async def failure_counts(self) -> dict[str, int]:
        return dict(self.failures)

    async def load_metadata(self) -> PipelineMetadata:
        return copied(self.metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        self.metadata = copied(metadata)
        self.saved_cursors.append(metadata.cursor)

    async def flush(self) -> None:
        self.flushes += 1
        if self.flush_fault is not None:
            raise self.flush_fault


class Sleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


@dataclasses.dataclass
class Run:
    listing: Any
    relevance: Any
    entities: Any
    exporter: Exporter
    state: State
    sleep: Sleep
    logged: list[str]
    events: list[PipelineEvent]
    pipeline: AsyncETLPipeline

    async def run(self, **arguments: Any) -> int:
        arguments.setdefault("query", "q")
        arguments.setdefault("sleep_between", 1.0)
        query = arguments.pop("query")
        return await self.pipeline.run(query, **arguments)


def build(
    listed: Iterable[RawRecord],
    *,
    irrelevant: Iterable[str] = (),
    failing: Iterable[str] = (),
    state: State | None = None,
    max_concurrency: int = 6,
    memory_ingestor: Any = None,
    shutdown: ShutdownSignal | None = None,
    listing: Any = None,
    relevance: AsyncRelevanceFilter | None = None,
    entities: AsyncEntityExtractor | None = None,
) -> Run:
    listing = listing or Listing(listed)
    relevance = relevance or Relevance(irrelevant)
    entities = entities or Entities(failing)
    exporter = Exporter()
    state = state or State()
    sleep = Sleep()
    logged: list[str] = []
    events: list[PipelineEvent] = []
    pipeline = AsyncETLPipeline(
        listing,
        relevance,
        entities,
        exporter,
        state,
        max_concurrency=max_concurrency,
        sleep=sleep,
        memory_ingestor=memory_ingestor,
        shutdown=shutdown,
        on_event=events.append,
    )
    pipeline._log = logged.append
    return Run(listing, relevance, entities, exporter, state, sleep, logged, events, pipeline)
