from __future__ import annotations

import asyncio

import pytest

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import RawRecord
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.state.async_base import AsyncStateManager


class TestMemoryIngestCancellation:
    @pytest.mark.asyncio
    async def test_cancellation_is_reraised_not_logged(self, mocker):
        ingestor = mocker.Mock()
        ingestor.ingest = mocker.AsyncMock(side_effect=asyncio.CancelledError())
        pipeline = AsyncETLPipeline(
            extractor=mocker.Mock(spec=AsyncExtractor),
            relevance_filter=mocker.Mock(spec=AsyncRelevanceFilter),
            entity_extractor=mocker.Mock(spec=AsyncEntityExtractor),
            exporter=mocker.Mock(spec=AsyncExporter),
            state_manager=mocker.Mock(spec=AsyncStateManager),
            destination="out.csv",
            memory_ingestor=ingestor,
        )
        with pytest.raises(asyncio.CancelledError):
            await pipeline._ingest_memory(RawRecord(record_id="a", title="t", abstract="abstract"), "body")
