from __future__ import annotations

import threading

import pytest

from sci_etl_core.exceptions import MalformedResponseError, PipelineAborted, UpstreamError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.state.async_base import AsyncStateManager


def _records(n: int) -> list[RawRecord]:
    return [RawRecord(record_id=str(i), title=f"t{i}", abstract=f"a{i}") for i in range(n)]


def _build(mocker, records, *, relevant=True, entities=None, max_workers=6):
    extractor = mocker.Mock(spec=AsyncExtractor)
    extractor.search = mocker.AsyncMock(return_value=b"<feed/>")
    extractor.parse_listing = mocker.Mock(
        side_effect=[(records, len(records))] + [([], 0)] * 10
    )
    extractor.fetch_full_text = mocker.AsyncMock(
        side_effect=lambda r: f"text-{r.record_id}"
    )

    relevance = mocker.Mock(spec=AsyncRelevanceFilter)
    relevance.is_relevant = mocker.AsyncMock(return_value=relevant)

    entity_extractor = mocker.Mock(spec=AsyncEntityExtractor)
    entity_extractor.extract = mocker.AsyncMock(
        return_value=entities if entities is not None else [{"name": "X"}]
    )

    exporter = mocker.Mock(spec=AsyncExporter)
    exporter.export = mocker.AsyncMock()

    state = mocker.Mock(spec=AsyncStateManager)
    state.load_processed_ids = mocker.AsyncMock(return_value=set())
    state.load_metadata = mocker.AsyncMock(
        return_value=PipelineMetadata(last_start_index=0)
    )
    state.mark_processed = mocker.AsyncMock()
    state.save_metadata = mocker.AsyncMock()

    pipeline = ETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entity_extractor,
        exporter=exporter,
        state_manager=state,
        destination="out.csv",
        max_concurrency=max_workers,
        sleep=mocker.AsyncMock(),
    )
    return pipeline, extractor, relevance, entity_extractor, exporter, state


class TestPipelineHappyPath:
    def test_processes_relevant_records_and_exports(self, mocker):
        pipeline, _, _, _, exporter, state = _build(mocker, _records(3))
        assert pipeline.run(query="q", max_records=3, sleep_between=0) == 3
        assert exporter.export.call_count == 3
        assert state.mark_processed.call_count == 3

    def test_skips_irrelevant_without_fetching_or_exporting(self, mocker):
        pipeline, extractor, _, _, exporter, state = _build(
            mocker, _records(2), relevant=False
        )
        assert pipeline.run(query="q", max_records=2, sleep_between=0) == 0
        extractor.fetch_full_text.assert_not_called()
        exporter.export.assert_not_called()
        assert state.mark_processed.call_count == 2

    def test_no_export_when_extraction_yields_nothing(self, mocker):
        pipeline, _, _, _, exporter, _ = _build(mocker, _records(2), entities=[])
        assert pipeline.run(query="q", max_records=2, sleep_between=0) == 2
        exporter.export.assert_not_called()

    def test_stops_when_listing_is_exhausted(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        pipeline.run(query="q", max_records=100, sleep_between=0)
        assert extractor.parse_listing.call_count >= 2

    def test_aborts_when_search_returns_no_payload(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        extractor.search = mocker.AsyncMock(return_value=None)
        with pytest.raises(PipelineAborted) as excinfo:
            pipeline.run(query="q", max_records=10, sleep_between=0)
        assert excinfo.value.partial_count == 0

    def test_persists_metadata_each_page(self, mocker):
        pipeline, _, _, _, _, state = _build(mocker, _records(2))
        pipeline.run(query="q", max_records=2, sleep_between=0)
        assert state.save_metadata.called


class TestPipelineFailureSignaling:
    def test_aborts_when_search_raises_upstream_and_keeps_partial_count(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(3))
        extractor.search = mocker.AsyncMock(
            side_effect=[b"<feed/>", UpstreamError("gateway down")]
        )
        with pytest.raises(PipelineAborted) as excinfo:
            pipeline.run(query="q", max_records=10, sleep_between=0)
        assert excinfo.value.partial_count == 3
        assert isinstance(excinfo.value.__cause__, UpstreamError)

    def test_aborts_when_parse_listing_reports_malformed(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(2))
        extractor.parse_listing = mocker.Mock(
            side_effect=[(_records(2), 2), MalformedResponseError("bad xml")]
        )
        with pytest.raises(PipelineAborted) as excinfo:
            pipeline.run(query="q", max_records=10, sleep_between=0)
        assert excinfo.value.partial_count == 2
        assert isinstance(excinfo.value.__cause__, MalformedResponseError)


class TestPipelineResilience:
    def test_one_record_failure_does_not_abort_run(self, mocker):
        pipeline, _, _, entity_extractor, _, _ = _build(mocker, _records(3))
        guard = threading.Lock()
        calls = {"n": 0}

        async def flaky(_text):
            with guard:
                calls["n"] += 1
                current = calls["n"]
            if current == 2:
                raise RuntimeError("extraction blew up")
            return [{"name": "ok"}]

        entity_extractor.extract = mocker.AsyncMock(side_effect=flaky)
        logged: list[str] = []
        pipeline._async._log = logged.append
        assert pipeline.run(query="q", max_records=3, sleep_between=0) >= 2
        assert any("failed" in m.lower() for m in logged)


class TestPipelineConcurrency:
    def test_shared_processed_ids_has_no_lost_updates(self, mocker):
        record_count = 200
        pipeline, _, _, _, _, state = _build(
            mocker, _records(record_count), max_workers=16
        )
        assert (
            pipeline.run(query="q", max_records=record_count, sleep_between=0)
            == record_count
        )
        marked = [call.args[0] for call in state.mark_processed.call_args_list]
        assert len(marked) == record_count
        assert len(set(marked)) == record_count

    def test_respects_max_records_ceiling_under_concurrency(self, mocker):
        pipeline, *_ = _build(mocker, _records(50), max_workers=8)
        processed = pipeline.run(query="q", max_records=10, sleep_between=0)
        assert 10 <= processed <= 50


class TestPipelineContextManager:
    def test_with_block_closes_resources(self, mocker):
        closeable = mocker.Mock()
        closeable.aclose = mocker.AsyncMock()
        extractor = mocker.Mock(spec=AsyncExtractor)
        pipeline = ETLPipeline(
            extractor=extractor,
            relevance_filter=mocker.Mock(spec=AsyncRelevanceFilter),
            entity_extractor=mocker.Mock(spec=AsyncEntityExtractor),
            exporter=mocker.Mock(spec=AsyncExporter),
            state_manager=mocker.Mock(spec=AsyncStateManager),
            destination="out.csv",
            closeables=[closeable, object()],
        )
        with pipeline as entered:
            assert entered is pipeline
        closeable.aclose.assert_called_once()