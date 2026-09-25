from __future__ import annotations

import pandas as pd

from legacy_paging import page_through_search
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.processors.dedup import DeduplicationStep, NeighborMatcher
from sci_etl_core.state.async_base import AsyncStateManager


def _pipeline(mocker, records, *, max_workers=4):
    extractor = mocker.Mock(spec=AsyncExtractor)
    extractor.search = mocker.AsyncMock(return_value=b"<feed/>")
    extractor.parse_listing = mocker.Mock(
        side_effect=[(records, len(records))] + [([], 0)] * 5
    )
    extractor.fetch_full_text = mocker.AsyncMock(
        side_effect=lambda r: f"text-{r.record_id}"
    )
    page_through_search(mocker, extractor)

    relevance = mocker.Mock(spec=AsyncRelevanceFilter)
    relevance.is_relevant = mocker.AsyncMock(return_value=True)

    entity = mocker.Mock(spec=AsyncEntityExtractor)
    entity.extract = mocker.AsyncMock(return_value=[{"name": "X"}])

    exporter = mocker.Mock(spec=AsyncExporter)
    exporter.export = mocker.AsyncMock()

    state = mocker.Mock(spec=AsyncStateManager)
    state.load_processed_ids = mocker.AsyncMock(return_value=set())
    state.load_metadata = mocker.AsyncMock(
        return_value=PipelineMetadata(cursor=None)
    )
    state.mark_processed = mocker.AsyncMock()
    state.failure_counts = mocker.AsyncMock(return_value={})

    pipeline = ETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entity,
        exporter=exporter,
        state_manager=state,
        destination="out.csv",
        max_concurrency=max_workers,
        sleep=mocker.AsyncMock(),
    )
    return pipeline, state


class TestPipelineEmptyRecordId:
    def test_record_without_id_is_skipped_because_it_cannot_be_tracked(self, mocker):
        pipeline, state = _pipeline(
            mocker, [RawRecord(record_id="", title="t", abstract="a")]
        )
        assert pipeline.run(query="q", page_size=1, total_limit=1, sleep_between=0) == 0
        state.mark_processed.assert_not_called()


class TestDedupRepeatDrop:
    def test_already_dropped_index_is_skipped(self):
        class RepeatDrop(NeighborMatcher):
            def find_matches(self, frame, threshold):
                return [(0, 2), (1, 2)]

        frame = pd.DataFrame(
            {"_norm_key": ["a", "b", "c"], "value": [None, None, 7.0]}
        )
        result = DeduplicationStep("_norm_key", matcher=RepeatDrop()).process(frame)
        assert len(result) == 2
        assert 7.0 in result["value"].to_numpy()
