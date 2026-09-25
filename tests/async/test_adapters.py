from __future__ import annotations

import threading
from typing import Any

import pytest

from sci_etl_core import (
    EntityExtractor,
    Exporter,
    Extractor,
    LLMClient,
    PipelineMetadata,
    RawRecord,
    RelevanceFilter,
    StateManager,
    SyncEntityExtractorAdapter,
    SyncExporterAdapter,
    SyncExtractorAdapter,
    SyncLLMClientAdapter,
    SyncRelevanceFilterAdapter,
    SyncStateManagerAdapter,
)
from sci_etl_core.pipeline_async import AsyncETLPipeline


class _Extractor(Extractor):
    def __init__(self) -> None:
        self.fetch_threads: list[threading.Thread] = []

    def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return f"{query}:{start_index}".encode()

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        if not raw_listing.endswith(b":0"):
            return [], 0
        records = [RawRecord(record_id=str(i), title=f"t{i}", abstract=f"a{i}") for i in range(3)]
        return [record for record in records if record.record_id not in seen_ids], len(records)

    def fetch_full_text(self, record: RawRecord) -> str:
        self.fetch_threads.append(threading.current_thread())
        return f"text-{record.record_id}"


class _Relevance(RelevanceFilter):
    def is_relevant(self, record: RawRecord) -> bool:
        return record.record_id != "1"


class _Entities(EntityExtractor):
    def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        return [{"name": text}]


class _Exporter(Exporter):
    def __init__(self) -> None:
        self.rows: list[tuple[str, Any]] = []

    def export(self, data: Any, destination: str) -> None:
        self.rows.extend((destination, row["name"]) for row in data)


class _State(StateManager):
    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.metadata = PipelineMetadata()

    def load_processed_ids(self) -> set[str]:
        return set(self.ids)

    def mark_processed(self, record_id: str) -> None:
        self.ids.add(record_id)

    def load_metadata(self) -> PipelineMetadata:
        return self.metadata

    def save_metadata(self, metadata: PipelineMetadata) -> None:
        self.metadata = metadata


class _LLM(LLMClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None, threading.Thread]] = []

    def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        self.calls.append((system_prompt, user_content, timeout, threading.current_thread()))
        return {"ok": True}


class TestSyncAdapters:
    @pytest.mark.asyncio
    async def test_extractor_adapter_runs_full_text_in_a_worker_thread(self):
        extractor = _Extractor()
        adapter = SyncExtractorAdapter(extractor)
        page = await adapter.fetch_page("q", None, 3)
        assert (len(page.records), page.entries, page.next_cursor) == (3, 3, "3")
        assert await adapter.fetch_full_text(page.records[0]) == "text-0"
        assert adapter.cursor_for_offset(3) == "3"
        assert extractor.fetch_threads[0] is not threading.current_thread()

    @pytest.mark.asyncio
    async def test_relevance_and_entity_adapters_delegate(self):
        assert (
            await SyncRelevanceFilterAdapter(_Relevance()).is_relevant(
                RawRecord(record_id="0", title="t", abstract="a")
            )
            is True
        )
        assert await SyncEntityExtractorAdapter(_Entities()).extract("body") == [{"name": "body"}]

    @pytest.mark.asyncio
    async def test_exporter_and_state_adapters_delegate(self):
        exporter, state = _Exporter(), _State()
        await SyncExporterAdapter(exporter).export([{"name": "x"}], "dest")
        adapter = SyncStateManagerAdapter(state)
        await adapter.mark_processed("7")
        await adapter.save_metadata(PipelineMetadata(cursor="4"))
        assert exporter.rows == [("dest", "x")]
        assert await adapter.load_processed_ids() == {"7"}
        assert (await adapter.load_metadata()).cursor == "4"

    @pytest.mark.asyncio
    async def test_llm_client_adapter_forwards_timeout_from_a_worker_thread(self):
        llm = _LLM()
        assert await SyncLLMClientAdapter(llm).complete_json("s", "u", 9) == {"ok": True}
        system, user, timeout, thread = llm.calls[0]
        assert (system, user, timeout) == ("s", "u", 9)
        assert thread is not threading.current_thread()

    @pytest.mark.asyncio
    async def test_pipeline_runs_on_sync_components(self):
        extractor, exporter, state = _Extractor(), _Exporter(), _State()
        pipeline = AsyncETLPipeline(
            extractor=SyncExtractorAdapter(extractor),
            relevance_filter=SyncRelevanceFilterAdapter(_Relevance()),
            entity_extractor=SyncEntityExtractorAdapter(_Entities()),
            exporter=SyncExporterAdapter(exporter),
            state_manager=SyncStateManagerAdapter(state),
            destination="out",
        )
        assert await pipeline.run(query="q", page_size=3, total_limit=10) == 2
        assert sorted(name for _, name in exporter.rows) == ["text-0", "text-2"]
        assert state.ids == {"0", "1", "2"}
        assert state.metadata.cursor == "3"
