from __future__ import annotations

import pytest

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.state.async_base import AsyncStateManager


def _pipeline(mocker, closeables):
    return ETLPipeline(
        extractor=mocker.Mock(spec=AsyncExtractor),
        relevance_filter=mocker.Mock(spec=AsyncRelevanceFilter),
        entity_extractor=mocker.Mock(spec=AsyncEntityExtractor),
        exporter=mocker.Mock(spec=AsyncExporter),
        state_manager=mocker.Mock(spec=AsyncStateManager),
        destination="out.csv",
        closeables=closeables,
    )


class TestPipelineCloseErrorHandling:
    def test_close_is_tolerated_when_bridge_loop_is_gone(self, mocker):
        closeable = mocker.Mock()
        closeable.aclose = mocker.AsyncMock()
        pipeline = _pipeline(mocker, [closeable])
        mocker.patch(
            "sci_etl_core.pipeline.run_sync", side_effect=RuntimeError("loop closed")
        )
        logged: list[str] = []
        mocker.patch.object(pipeline._async, "log", side_effect=logged.append)

        with pipeline:
            pass

        assert any("Resource close skipped" in message for message in logged)
