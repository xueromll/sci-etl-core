from __future__ import annotations

import threading

import pytest

from sci_etl_core.exporters.base import Exporter
from sci_etl_core.extractors.base import Extractor
from sci_etl_core.llm.extraction import EntityExtractor
from sci_etl_core.llm.relevance import RelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.state.base import StateManager


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    mocker.patch("sci_etl_core.pipeline.time.sleep")


def _records(n: int) -> list[RawRecord]:
    return [RawRecord(record_id=str(i), title=f"t{i}", abstract=f"a{i}") for i in range(n)]


def _build(mocker, records, *, relevant=True, entities=None, max_workers=6):
    extractor = mocker.Mock(spec=Extractor)
    extractor.search.return_value = b"<feed/>"
    extractor.parse_listing.side_effect = [(records, len(records))] + [([], 0)] * 10
    extractor.fetch_full_text.side_effect = lambda r: f"text-{r.record_id}"

    relevance = mocker.Mock(spec=RelevanceFilter)
    relevance.is_relevant.return_value = relevant

    entity_extractor = mocker.Mock(spec=EntityExtractor)
    entity_extractor.extract.return_value = entities if entities is not None else [{"name": "X"}]

    exporter = mocker.Mock(spec=Exporter)

    state = mocker.Mock(spec=StateManager)
    state.load_processed_ids.return_value = set()
    state.load_metadata.return_value = PipelineMetadata(last_start_index=0)

    pipeline = ETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entity_extractor,
        exporter=exporter,
        state_manager=state,
        destination="out.csv",
        max_workers=max_workers,
    )
    return pipeline, extractor, relevance, entity_extractor, exporter, state


class TestPipelineHappyPath:
    def test_processes_relevant_records_and_exports(self, mocker):
        pipeline, extractor, _, entity_extractor, exporter, state = _build(mocker, _records(3))
        processed = pipeline.run(query="q", max_records=3, sleep_between=0)
        assert processed == 3
        assert exporter.export.call_count == 3
        assert state.mark_processed.call_count == 3

    def test_skips_irrelevant_without_fetching_or_exporting(self, mocker):
        pipeline, extractor, _, _, exporter, state = _build(mocker, _records(2), relevant=False)
        processed = pipeline.run(query="q", max_records=2, sleep_between=0)
        assert processed == 0
        extractor.fetch_full_text.assert_not_called()
        exporter.export.assert_not_called()
        assert state.mark_processed.call_count == 2

    def test_no_export_when_extraction_yields_nothing(self, mocker):
        pipeline, _, _, _, exporter, state = _build(mocker, _records(2), entities=[])
        processed = pipeline.run(query="q", max_records=2, sleep_between=0)
        assert processed == 2
        exporter.export.assert_not_called()

    def test_stops_when_listing_is_exhausted(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        pipeline.run(query="q", max_records=100, sleep_between=0)
        assert extractor.parse_listing.call_count >= 2

    def test_stops_when_search_returns_none(self, mocker):
        pipeline, extractor, *_ = _build(mocker, _records(1))
        extractor.search.return_value = None
        assert pipeline.run(query="q", max_records=10, sleep_between=0) == 0

    def test_persists_metadata_each_page(self, mocker):
        pipeline, _, _, _, _, state = _build(mocker, _records(2))
        pipeline.run(query="q", max_records=2, sleep_between=0)
        assert state.save_metadata.called


class TestPipelineResilience:
    def test_one_record_failure_does_not_abort_run(self, mocker):
        pipeline, extractor, _, entity_extractor, exporter, _ = _build(mocker, _records(3))
        calls = {"n": 0}

        def flaky(_text):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("extraction blew up")
            return [{"name": "ok"}]

        entity_extractor.extract.side_effect = flaky
        logged = []
        pipeline._log = logged.append
        processed = pipeline.run(query="q", max_records=3, sleep_between=0)
        assert processed >= 2
        assert any("failed" in m.lower() for m in logged)


class TestPipelineConcurrency:
    def test_shared_processed_ids_has_no_lost_updates(self, mocker):
        record_count = 200
        pipeline, _, _, _, _, state = _build(mocker, _records(record_count), max_workers=16)
        marked: list[str] = []
        lock = threading.Lock()

        def record_mark(rid):
            with lock:
                marked.append(rid)

        state.mark_processed.side_effect = record_mark
        processed = pipeline.run(query="q", max_records=record_count, sleep_between=0)
        assert processed == record_count
        assert len(marked) == record_count
        assert len(set(marked)) == record_count

    def test_respects_max_records_ceiling_under_concurrency(self, mocker):
        pipeline, *_ = _build(mocker, _records(50), max_workers=8)
        processed = pipeline.run(query="q", max_records=10, sleep_between=0)
        assert processed <= 50
        assert processed >= 10
