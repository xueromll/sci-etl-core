from __future__ import annotations

import pytest

from sci_etl_core.exceptions import LLMError, MalformedResponseError, PipelineAborted, UpstreamError
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
    async def test_persists_metadata_each_page(self, mocker):
        pipeline, _, _, _, _, state = _build(mocker, _records(2))
        await pipeline.run(query="q", max_records=2, sleep_between=0)
        assert state.save_metadata.await_count >= 1

    @pytest.mark.asyncio
    async def test_record_without_id_is_not_marked(self, mocker):
        pipeline, _, _, _, _, state = _build(mocker, [RawRecord(record_id="", title="t", abstract="a")])
        assert await pipeline.run(query="q", max_records=1, sleep_between=0) == 1
        state.mark_processed.assert_not_awaited()


class TestAsyncPipelineFailureSignaling:
    @pytest.mark.asyncio
    async def test_aborts_when_search_returns_no_payload(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        extractor.search = mocker.AsyncMock(return_value=None)
        with pytest.raises(PipelineAborted, match="no payload") as excinfo:
            await pipeline.run(query="q", max_records=10, sleep_between=0)
        assert excinfo.value.partial_count == 0

    @pytest.mark.asyncio
    async def test_aborts_when_search_raises_upstream_and_keeps_partial_count(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(3))
        extractor.search = mocker.AsyncMock(side_effect=[b"<feed/>", UpstreamError("gateway down")])
        with pytest.raises(PipelineAborted) as excinfo:
            await pipeline.run(query="q", max_records=10, sleep_between=0)
        assert excinfo.value.partial_count == 3
        assert isinstance(excinfo.value.__cause__, UpstreamError)

    @pytest.mark.asyncio
    async def test_aborts_when_parse_listing_reports_malformed(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(2))
        extractor.parse_listing = mocker.Mock(
            side_effect=[(_records(2), 2), MalformedResponseError("bad xml")]
        )
        with pytest.raises(PipelineAborted, match="malformed") as excinfo:
            await pipeline.run(query="q", max_records=10, sleep_between=0)
        assert excinfo.value.partial_count == 2
        assert isinstance(excinfo.value.__cause__, MalformedResponseError)

    @pytest.mark.asyncio
    async def test_empty_listing_is_the_only_clean_termination(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        assert await pipeline.run(query="q", max_records=100, sleep_between=0) == 1
        assert extractor.search.await_count == 2


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

    @pytest.mark.asyncio
    async def test_extraction_llm_failure_leaves_record_for_retry(self, mocker):
        pipeline, _, _, entity, exporter, state = _build(mocker, _records(1))
        entity.extract = mocker.AsyncMock(side_effect=LLMError("outage"))
        logged: list[str] = []
        pipeline._log = logged.append
        assert await pipeline.run(query="q", max_records=1, sleep_between=0) == 0
        state.mark_processed.assert_not_awaited()
        exporter.export.assert_not_called()
        assert any("LLMError" in message for message in logged)


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

    def test_log_forwards_to_the_injected_logger(self, mocker):
        pipeline, *_ = _build(mocker, _records(0))
        logged: list[str] = []
        pipeline._log = logged.append
        pipeline.log("hello")
        assert logged == ["hello"]


class TestAsyncPipelineResume:
    @pytest.mark.asyncio
    async def test_page_of_processed_records_does_not_end_the_run(self, mocker):
        pipeline, extractor, _, _, _, state = _build(mocker, [])
        fresh = _records(3)[2:]
        extractor.parse_listing = mocker.Mock(side_effect=[([], 2), (fresh, 1), ([], 0)])
        assert await pipeline.run(query="q", page_size=2, total_limit=10) == 1
        assert [call.args[2] for call in extractor.search.await_args_list] == [0, 2, 3]
        assert state.save_metadata.await_args.args[0].last_start_index == 3

    @pytest.mark.asyncio
    async def test_saved_offset_is_used_by_default(self, mocker):
        pipeline, extractor, _, _, _, state = _build(mocker, _records(1))
        state.load_metadata = mocker.AsyncMock(return_value=PipelineMetadata(last_start_index=40))
        await pipeline.run(query="q", page_size=5, total_limit=5)
        assert extractor.search.await_args_list[0].args[2] == 40

    @pytest.mark.asyncio
    async def test_start_index_overrides_saved_offset(self, mocker):
        pipeline, extractor, _, _, _, state = _build(mocker, _records(1))
        state.load_metadata = mocker.AsyncMock(return_value=PipelineMetadata(last_start_index=40))
        await pipeline.run(query="q", page_size=5, total_limit=5, start_index=0)
        assert extractor.search.await_args_list[0].args[2] == 0

    @pytest.mark.asyncio
    async def test_negative_start_index_is_rejected(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        with pytest.raises(ValueError, match="start_index"):
            await pipeline.run(query="q", start_index=-1)
        extractor.search.assert_not_awaited()
