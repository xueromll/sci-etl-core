"""In-memory collaborators for the run-semantics tests.

Each fake records what the pipeline asked of it, so a rule's test can assert
on requests, saved offsets, and marked records instead of on mock call lists.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable
from typing import Any

from sci_etl_core.exceptions import LLMError, MalformedResponseError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.observability import PipelineEvent
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.signals import ShutdownSignal
from sci_etl_core.state.async_base import AsyncStateManager

MALFORMED = b"malformed"


def records(*record_ids: str) -> list[RawRecord]:
    return [RawRecord(record_id=record_id, title=f"title {record_id}", abstract="abstract") for record_id in record_ids]


class OffsetListing(AsyncExtractor):
    """A listing served by offset from a list of records, like arXiv's.

    With ``cap`` set, no entry at or past that offset is served, as OpenAlex
    and PubMed stop at 10,000 results.
    """

    def __init__(self, listed: Iterable[RawRecord]) -> None:
        self.listed = list(listed)
        self.requests: list[int] = []
        self.parses = 0
        self.search_faults: dict[int, BaseException] = {}
        self.missing_payloads: set[int] = set()
        self.malformed_pages: set[int] = set()
        self.cap: int | None = None

    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        self.requests.append(start_index)
        if start_index in self.search_faults:
            raise self.search_faults[start_index]
        if start_index in self.missing_payloads:
            return None
        if start_index in self.malformed_pages:
            return MALFORMED
        end = start_index + max_results if self.cap is None else min(start_index + max_results, self.cap)
        page = self.listed[start_index:end]
        return json.dumps([dataclasses.asdict(record) for record in page]).encode()

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        self.parses += 1
        if raw_listing == MALFORMED:
            raise MalformedResponseError("unreadable listing")
        entries = [RawRecord(**entry) for entry in json.loads(raw_listing)]
        return [entry for entry in entries if entry.record_id not in seen_ids], len(entries)

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
        self.saved_offsets: list[int] = []
        self.flushes = 0
        self.flush_fault: BaseException | None = None

    async def load_processed_ids(self) -> set[str]:
        return set(self.processed)

    async def mark_processed(self, record_id: str) -> None:
        self.processed.add(record_id)
        self.marked.append(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return copied(self.metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        self.metadata = copied(metadata)
        self.saved_offsets.append(metadata.last_start_index)

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
    listing: OffsetListing
    relevance: Relevance
    entities: Entities
    exporter: Exporter
    state: State
    sleep: Sleep
    logged: list[str]
    events: list[PipelineEvent]
    pipeline: AsyncETLPipeline

    async def run(self, **arguments: Any) -> int:
        arguments.setdefault("query", "q")
        arguments.setdefault("sleep_between", 1.0)
        return await self.pipeline.run(**arguments)


def build(
    listed: Iterable[RawRecord],
    *,
    irrelevant: Iterable[str] = (),
    failing: Iterable[str] = (),
    state: State | None = None,
    max_concurrency: int = 6,
    memory_ingestor: Any = None,
    shutdown: ShutdownSignal | None = None,
) -> Run:
    listing = OffsetListing(listed)
    relevance = Relevance(irrelevant)
    entities = Entities(failing)
    exporter = Exporter()
    state = state or State()
    sleep = Sleep()
    logged: list[str] = []
    events: list[PipelineEvent] = []
    pipeline = AsyncETLPipeline(
        extractor=listing,
        relevance_filter=relevance,
        entity_extractor=entities,
        exporter=exporter,
        state_manager=state,
        destination="unused",
        max_concurrency=max_concurrency,
        logger=logged.append,
        sleep=sleep,
        memory_ingestor=memory_ingestor,
        shutdown=shutdown,
        on_event=events.append,
    )
    return Run(listing, relevance, entities, exporter, state, sleep, logged, events, pipeline)
