from __future__ import annotations

import asyncio

import pytest

from sci_etl_core.exceptions import (
    ExtractionError,
    LLMError,
    MalformedResponseError,
    PipelineAborted,
    UpstreamError,
)
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.state.async_base import AsyncStateManager


def _records(n: int, start: int = 0) -> list[RawRecord]:
    return [RawRecord(record_id=str(i), title=f"t{i}", abstract=f"a{i}") for i in range(start, start + n)]


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


def _marked(state) -> list[str]:
    return [call.args[0] for call in state.mark_processed.await_args_list]


def _saved_offset(state) -> int:
    return state.save_metadata.await_args.args[0].last_start_index


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

    @pytest.mark.parametrize("record_id", ["", "   "])
    @pytest.mark.asyncio
    async def test_record_without_a_trackable_id_is_skipped_and_logged(self, mocker, record_id):
        pipeline, _, relevance, _, _, state = _build(
            mocker, [RawRecord(record_id=record_id, title="t", abstract="a")]
        )
        logged: list[str] = []
        pipeline._log = logged.append
        assert await pipeline.run(query="q", max_records=1, sleep_between=0) == 0
        relevance.is_relevant.assert_not_awaited()
        state.mark_processed.assert_not_awaited()
        assert any("no record_id" in message for message in logged)
        assert _saved_offset(state) == 1


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
    async def test_aborts_when_the_source_rejects_the_listing_request(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        extractor.search = mocker.AsyncMock(side_effect=ExtractionError("status 400"))
        with pytest.raises(PipelineAborted, match="Listing fetch failed") as excinfo:
            await pipeline.run(query="q", max_records=5, sleep_between=0)
        assert isinstance(excinfo.value.__cause__, ExtractionError)

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
        with pytest.raises(PipelineAborted) as excinfo:
            await pipeline.run(query="q", max_records=1, sleep_between=0)
        assert isinstance(excinfo.value.__cause__, LLMError)
        state.mark_processed.assert_not_awaited()
        exporter.export.assert_not_called()
        assert any("LLMError" in message for message in logged)


class TestAsyncPipelineOffsetIntegrity:
    @pytest.mark.asyncio
    async def test_failed_record_holds_the_saved_offset_at_its_page(self, mocker):
        pipeline, extractor, _, entity, _, state = _build(mocker, [])
        extractor.parse_listing = mocker.Mock(
            side_effect=[(_records(2), 2), (_records(2, start=2), 2), ([], 0)]
        )

        async def extract(text):
            if text == "text-0":
                raise UpstreamError("transient")
            return [{"name": text}]

        entity.extract = mocker.AsyncMock(side_effect=extract)
        assert await pipeline.run(query="q", page_size=2, total_limit=10) == 3
        assert state.save_metadata.await_count == 2
        assert _saved_offset(state) == 0
        assert "0" not in _marked(state)

    @pytest.mark.asyncio
    async def test_page_where_nothing_could_be_processed_aborts_when_the_listing_ends(self, mocker):
        pipeline, extractor, relevance, entity, _, state = _build(mocker, _records(3))
        relevance.is_relevant = mocker.AsyncMock(side_effect=lambda record: record.record_id != "2")
        entity.extract = mocker.AsyncMock(side_effect=LLMError("401 invalid api key"))
        with pytest.raises(PipelineAborted, match="could be processed") as excinfo:
            await pipeline.run(query="q", page_size=3, total_limit=10)
        assert excinfo.value.partial_count == 0
        assert isinstance(excinfo.value.__cause__, LLMError)
        assert _marked(state) == ["2"]
        assert extractor.search.await_count == 2
        assert _saved_offset(state) == 0

    @pytest.mark.asyncio
    async def test_record_cancelled_on_its_own_is_a_failure_not_progress(self, mocker):
        pipeline, _, relevance, _, _, state = _build(mocker, _records(2))

        async def gate(record):
            if record.record_id == "0":
                raise asyncio.CancelledError()
            return True

        relevance.is_relevant = mocker.AsyncMock(side_effect=gate)
        logged: list[str] = []
        pipeline._log = logged.append
        assert await pipeline.run(query="q", page_size=2, total_limit=10) == 1
        assert _marked(state) == ["1"]
        assert any("CancelledError" in message for message in logged)
        assert _saved_offset(state) == 0


class TestAsyncPipelineStalledPages:
    @pytest.mark.asyncio
    async def test_lone_failure_on_a_mostly_irrelevant_page_does_not_abort(self, mocker):
        pipeline, extractor, relevance, _, _, state = _build(mocker, [])
        extractor.parse_listing = mocker.Mock(
            side_effect=[(_records(20), 20), (_records(2, start=20), 2), ([], 0)]
        )
        relevance.is_relevant = mocker.AsyncMock(
            side_effect=lambda record: record.record_id in {"0", "20", "21"}
        )

        async def fetch(record):
            if record.record_id == "0":
                raise UpstreamError("arXiv returned status 503")
            return f"text-{record.record_id}"

        extractor.fetch_full_text = mocker.AsyncMock(side_effect=fetch)
        assert await pipeline.run(query="q", page_size=20, total_limit=10) == 2
        assert "0" not in _marked(state)
        assert _saved_offset(state) == 0

    @pytest.mark.asyncio
    async def test_second_page_without_progress_aborts_before_the_next_request(self, mocker):
        pipeline, extractor, _, entity, _, _ = _build(mocker, [])
        extractor.parse_listing = mocker.Mock(
            side_effect=[(_records(2), 2), (_records(2, start=2), 2), (_records(2, start=4), 2), ([], 0)]
        )
        entity.extract = mocker.AsyncMock(side_effect=LLMError("401 invalid api key"))
        with pytest.raises(PipelineAborted, match="could be processed") as excinfo:
            await pipeline.run(query="q", page_size=2, total_limit=10)
        assert excinfo.value.partial_count == 0
        assert isinstance(excinfo.value.__cause__, LLMError)
        assert extractor.search.await_count == 2

    @pytest.mark.asyncio
    async def test_page_without_failures_does_not_clear_an_earlier_stall(self, mocker):
        pipeline, extractor, relevance, entity, _, _ = _build(mocker, [])
        extractor.parse_listing = mocker.Mock(
            side_effect=[(_records(1, start=n), 1) for n in range(4)] + [([], 0)]
        )
        relevance.is_relevant = mocker.AsyncMock(side_effect=lambda record: record.record_id != "1")
        entity.extract = mocker.AsyncMock(side_effect=LLMError("401 invalid api key"))
        with pytest.raises(PipelineAborted, match="could be processed"):
            await pipeline.run(query="q", page_size=1, total_limit=10)
        assert extractor.search.await_count == 3


class TestAsyncPipelineCeiling:
    @pytest.mark.asyncio
    async def test_total_limit_is_exact_under_concurrency(self, mocker):
        pipeline, _, _, _, _, state = _build(mocker, _records(50), max_concurrency=8)
        assert await pipeline.run(query="q", max_records=10, sleep_between=0) == 10
        assert state.mark_processed.await_count == 10
        assert _saved_offset(state) == 0

    @pytest.mark.asyncio
    async def test_records_after_the_limit_skip_the_relevance_call(self, mocker):
        pipeline, _, relevance, _, _, state = _build(mocker, _records(5), max_concurrency=1)
        assert await pipeline.run(query="q", page_size=5, total_limit=2) == 2
        assert relevance.is_relevant.await_count == 2
        assert _marked(state) == ["0", "1"]

    @pytest.mark.asyncio
    async def test_records_racing_through_the_relevance_gate_cannot_overshoot(self, mocker):
        pipeline, _, relevance, _, _, state = _build(mocker, _records(4), max_concurrency=4)

        async def slow_gate(_record):
            await asyncio.sleep(0)
            return True

        relevance.is_relevant = mocker.AsyncMock(side_effect=slow_gate)
        assert await pipeline.run(query="q", page_size=4, total_limit=1) == 1
        assert relevance.is_relevant.await_count == 4
        assert state.mark_processed.await_count == 1

    @pytest.mark.asyncio
    async def test_failed_record_frees_its_slot_for_the_next(self, mocker):
        pipeline, _, _, entity, _, state = _build(mocker, _records(2), max_concurrency=1)
        entity.extract = mocker.AsyncMock(side_effect=[LLMError("once"), [{"name": "ok"}]])
        assert await pipeline.run(query="q", page_size=2, total_limit=1) == 1
        assert _marked(state) == ["1"]


class TestAsyncPipelinePacing:
    @pytest.mark.asyncio
    async def test_sleeps_between_pages(self, mocker):
        pipeline, *_ = _build(mocker, _records(1))
        assert await pipeline.run(query="q", page_size=5, total_limit=5, sleep_between=5.0) == 1
        assert pipeline._sleep.await_args_list == [mocker.call(5.0)]

    @pytest.mark.asyncio
    async def test_no_sleep_after_the_page_that_reaches_the_limit(self, mocker):
        pipeline, *_ = _build(mocker, _records(2))
        assert await pipeline.run(query="q", page_size=2, total_limit=2, sleep_between=5.0) == 2
        pipeline._sleep.assert_not_awaited()


class TestAsyncPipelineConcurrency:
    @pytest.mark.asyncio
    async def test_shared_ids_no_lost_updates(self, mocker):
        count = 200
        pipeline, _, _, _, _, state = _build(mocker, _records(count), max_concurrency=16)
        assert await pipeline.run(query="q", max_records=count, sleep_between=0) == count
        marked = _marked(state)
        assert len(marked) == count
        assert len(set(marked)) == count


class TestAsyncPipelineContextManager:
    @pytest.mark.asyncio
    async def test_async_with_closes_resources(self, mocker):
        closeable = mocker.Mock()
        closeable.aclose = mocker.AsyncMock()
        pipeline, *_ = _build(mocker, _records(0))
        pipeline._closeables = [closeable, object()]
        async with pipeline as entered:
            assert entered is pipeline
        closeable.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_failure_does_not_stop_later_closes_and_is_raised(self, mocker):
        failing = mocker.Mock()
        failing.aclose = mocker.AsyncMock(side_effect=OSError("close failed"))
        healthy = mocker.Mock()
        healthy.aclose = mocker.AsyncMock()
        pipeline, *_ = _build(mocker, _records(0))
        pipeline._closeables = [failing, healthy]
        with pytest.raises(OSError, match="close failed"):
            async with pipeline:
                pass
        healthy.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_failure_never_masks_the_block_exception(self, mocker):
        failing = mocker.Mock()
        failing.aclose = mocker.AsyncMock(side_effect=OSError("close failed"))
        pipeline, *_ = _build(mocker, _records(0))
        pipeline._closeables = [failing]
        logged: list[str] = []
        pipeline._log = logged.append
        with pytest.raises(RuntimeError, match="original"):
            async with pipeline:
                raise RuntimeError("original")
        assert any("Resource close failed" in message for message in logged)

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
        assert _saved_offset(state) == 3

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


class TestAsyncPipelineArgumentValidation:
    @pytest.mark.parametrize("max_concurrency", [0, -1])
    def test_max_concurrency_below_one_is_rejected(self, mocker, max_concurrency):
        with pytest.raises(ValueError, match="max_concurrency"):
            _build(mocker, [], max_concurrency=max_concurrency)

    @pytest.mark.parametrize(
        ("limits", "message"),
        [
            ({"page_size": 0}, "page_size"),
            ({"max_records": 0}, "page_size"),
            ({"total_limit": -1}, "total_limit"),
        ],
    )
    @pytest.mark.asyncio
    async def test_out_of_range_limits_are_rejected_before_any_request(self, mocker, limits, message):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        with pytest.raises(ValueError, match=message):
            await pipeline.run(query="q", **limits)
        extractor.search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_zero_total_limit_processes_nothing(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        assert await pipeline.run(query="q", page_size=5, total_limit=0) == 0
        extractor.search.assert_not_awaited()
