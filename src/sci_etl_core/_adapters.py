from __future__ import annotations

import asyncio
from typing import Any

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.exporters.base import Exporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.extractors.base import Extractor
from sci_etl_core.llm.base import EntityExtractor, RelevanceFilter
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.base import StateManager

__all__ = [
    "SyncEntityExtractorAdapter",
    "SyncExporterAdapter",
    "SyncExtractorAdapter",
    "SyncRelevanceFilterAdapter",
    "SyncStateManagerAdapter",
]


class SyncExtractorAdapter(AsyncExtractor):
    """Expose a synchronous extractor through the async extractor contract.

    Per-record full-text retrieval is dispatched to a worker thread so the
    orchestrator keeps real fan-out; listing calls stay on the loop because they
    are inherently sequential.
    """

    def __init__(self, extractor: Extractor) -> None:
        self._extractor = extractor

    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return self._extractor.search(query, max_results, start_index)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        return self._extractor.parse_listing(raw_listing, seen_ids)

    async def fetch_full_text(self, record: RawRecord) -> str:
        return await asyncio.to_thread(self._extractor.fetch_full_text, record)


class SyncRelevanceFilterAdapter(AsyncRelevanceFilter):
    def __init__(self, relevance_filter: RelevanceFilter) -> None:
        self._relevance_filter = relevance_filter

    async def is_relevant(self, record: RawRecord) -> bool:
        return await asyncio.to_thread(self._relevance_filter.is_relevant, record)


class SyncEntityExtractorAdapter(AsyncEntityExtractor):
    def __init__(self, entity_extractor: EntityExtractor) -> None:
        self._entity_extractor = entity_extractor

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._entity_extractor.extract, text)


class SyncExporterAdapter(AsyncExporter):
    """Serialize exports on the loop thread so concurrent writes cannot interleave."""

    def __init__(self, exporter: Exporter) -> None:
        self._exporter = exporter

    async def export(self, data: Any, destination: str) -> None:
        self._exporter.export(data, destination)


class SyncStateManagerAdapter(AsyncStateManager):
    """Serialize state mutations on the loop thread to avoid lost updates."""

    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    async def load_processed_ids(self) -> set[str]:
        return self._state_manager.load_processed_ids()

    async def mark_processed(self, record_id: str) -> None:
        self._state_manager.mark_processed(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return self._state_manager.load_metadata()

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        self._state_manager.save_metadata(metadata)
