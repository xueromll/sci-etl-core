from __future__ import annotations

import pytest

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.state.async_base import AsyncStateManager


def _records(n: int) -> list[RawRecord]:
    return [RawRecord(record_id=str(i), title=f"t{i}", abstract=f"a{i}") for i in range(n)]


def _build(mocker, records, *, relevant=True, entities=None, max_concurrency=6):
    extractor = mocker.Mock(spec=AsyncExtractor)
    extractor.search = mocker.AsyncMock(return_value=b"<feed/>")
    extractor.parse_listing = mocker.Mock(side_effect=[(records, len(records))] + [([], 0)] * 10)
    extractor.fetch_full_text = mocker.AsyncMock(side_effect=lambda r: f"text-{r.record_id}")

    relevance = mocker.Mock(spec=AsyncRelevanceFilter)
    relevance.is_relevant = mocker.AsyncMock(return_value=relevant)

    entity = mocker.Mock(spec=AsyncEntityExtractor)
    entity.extract = mocker.AsyncMock(return_value=entities if entities is not None else [{"name": "X"}])

    exporter = mocker.Mock(spec=AsyncExporter)
    exporter.export = mocker.AsyncMock()

    state = mocker.Mock(spec=AsyncStateManager)
    state.load_processed_ids = mocker.AsyncMock(return_value=set())
    state.load_metadata = mocker.AsyncMock(return_value=PipelineMetadata(last_start_index=0))
    state.mark_processed = mocker.AsyncMock()
    state.save_metadata = mocker.AsyncMock()

    pipeline = AsyncETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entity,
        exporter=exporter,
        state_manager=state,
        destination="out.csv",
        max_concurrency=max_concurrency,
        sleep=mocker.AsyncMock(),
    )
    return pipeline, extractor, relevance, entity, exporter, state


class TestAsyncPipelineHappyPath:
    @pytest.mark.asyncio
    async def test_processes_relevant_records_and_exports(self, mocker):
        pipeline, _, _, _, exporter, state = _build(mocker, _records(3))
        assert await pipeline.run(query="q", max_records=3, sleep_between=0) == 3
        assert exporter.export.await_count == 3
        assert state.mark_processed.await_count == 3

    @pytest.mark.asyncio
    async def test_skips_irrelevant(self, mocker):
        pipeline, extractor, _, _, exporter, state = _build(mocker, _records(2), relevant=False)
        assert await pipeline.run(query="q", max_records=2, sleep_between=0) == 0
        extractor.fetch_full_text.assert_not_called()
        exporter.export.assert_not_called()
        assert state.mark_processed.await_count == 2

    @pytest.mark.asyncio
    async def test_no_export_when_extraction_empty(self, mocker):
        pipeline, _, _, _, exporter, _ = _build(mocker, _records(2), entities=[])
        assert await pipeline.run(query="q", max_records=2, sleep_between=0) == 2
        exporter.export.assert_not_called()

    @pytest.mark.asyncio
    async def test_stops_when_listing_exhausted(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        await pipeline.run(query="q", max_records=100, sleep_between=0)
        assert extractor.parse_listing.call_count >= 2

    @pytest.mark.asyncio
    async def test_stops_when_search_returns_none(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        extractor.search = mocker.AsyncMock(return_value=None)
        assert await pipeline.run(query="q", max_records=10, sleep_between=0) == 0

    @pytest.mark.asyncio
    async def test_persists_metadata_each_page(self, mocker):
        pipeline, _, _, _, _, state = _build(mocker, _records(2))
        await pipeline.run(query="q", max_records=2, sleep_between=0)
        assert state.save_metadata.await_count >= 1


class TestAsyncPipelineResilience:
    @pytest.mark.asyncio
    async def test_one_failure_does_not_abort_run(self, mocker):
        pipeline, _, _, entity, _, _ = _build(mocker, _records(3))
        calls = {"n": 0}

        async def flaky(_text):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("extraction blew up")
            return [{"name": "ok"}]

        entity.extract = mocker.AsyncMock(side_effect=flaky)
        logged: list[str] = []
        pipeline._log = logged.append
        assert await pipeline.run(query="q", max_records=3, sleep_between=0) >= 2
        assert any("failed" in m.lower() for m in logged)


class TestAsyncPipelineConcurrency:
    @pytest.mark.asyncio
    async def test_shared_ids_no_lost_updates(self, mocker):
        count = 200
        pipeline, _, _, _, _, state = _build(mocker, _records(count), max_concurrency=16)
        assert await pipeline.run(query="q", max_records=count, sleep_between=0) == count
        marked = [call.args[0] for call in state.mark_processed.await_args_list]
        assert len(marked) == count
        assert len(set(marked)) == count

    @pytest.mark.asyncio
    async def test_respects_max_records_ceiling(self, mocker):
        pipeline, *_ = _build(mocker, _records(50), max_concurrency=8)
        processed = await pipeline.run(query="q", max_records=10, sleep_between=0)
        assert 10 <= processed <= 50


class TestAsyncPipelineContextManager:
    @pytest.mark.asyncio
    async def test_async_with_closes_resources(self, mocker):
        closeable = mocker.Mock()
        closeable.aclose = mocker.AsyncMock()
        pipeline, *_ = _build(mocker, _records(0))
        pipeline._closeables = [closeable]
        async with pipeline as entered:
            assert entered is pipeline
        closeable.aclose.assert_awaited_once()
