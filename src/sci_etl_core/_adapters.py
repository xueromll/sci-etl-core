from __future__ import annotations

import asyncio
from typing import Any

from sci_etl_core._deprecation import warn_deprecated
from sci_etl_core.exceptions import UpstreamError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.exporters.base import Exporter
from sci_etl_core.extractors._offsets import decimal_cursor, offset_from_cursor, offset_page
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.extractors.base import Extractor
from sci_etl_core.llm.base import EntityExtractor, RelevanceFilter
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import ListingPage, PipelineMetadata, RawRecord
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.base import StateManager

__all__ = [
    "SyncEntityExtractorAdapter",
    "SyncExporterAdapter",
    "SyncExtractorAdapter",
    "SyncRelevanceFilterAdapter",
    "SyncStateManagerAdapter",
]


def _warn_adapter(name: str, replacement: str) -> None:
    warn_deprecated(name, f"implement {replacement} instead", stacklevel=3)


class SyncExtractorAdapter(AsyncExtractor):
    """Expose a synchronous extractor through the async extractor contract.

    Its cursors are decimal offsets passed to the wrapped ``search`` as its
    start index, and a page with no entries ends the listing. Per-record
    full-text retrieval is dispatched to a worker thread so the orchestrator
    keeps real fan-out; listing calls stay on the loop because they are
    inherently sequential.

    .. deprecated:: 0.5.0
        The blocking contracts and their adapters will be removed in 0.6.0.
    """

    def __init__(self, extractor: Extractor) -> None:
        _warn_adapter("SyncExtractorAdapter", "AsyncExtractor")
        self._extractor = extractor

    def cursor_for_offset(self, offset: int) -> str:
        return decimal_cursor(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = offset_from_cursor(cursor)
        raw_listing = self._extractor.search(query, page_size, offset)
        if not raw_listing:
            raise UpstreamError(f"The listing fetch at offset {offset} returned no payload")
        records, entries = self._extractor.parse_listing(raw_listing, set())
        return offset_page(records, entries, offset)

    async def fetch_full_text(self, record: RawRecord) -> str:
        return await asyncio.to_thread(self._extractor.fetch_full_text, record)


class SyncRelevanceFilterAdapter(AsyncRelevanceFilter):
    """Expose a synchronous relevance filter through the async contract.

    .. deprecated:: 0.5.0
        The blocking contracts and their adapters will be removed in 0.6.0.
    """

    def __init__(self, relevance_filter: RelevanceFilter) -> None:
        _warn_adapter("SyncRelevanceFilterAdapter", "AsyncRelevanceFilter")
        self._relevance_filter = relevance_filter

    async def is_relevant(self, record: RawRecord) -> bool:
        return await asyncio.to_thread(self._relevance_filter.is_relevant, record)


class SyncEntityExtractorAdapter(AsyncEntityExtractor):
    """Expose a synchronous entity extractor through the async contract.

    .. deprecated:: 0.5.0
        The blocking contracts and their adapters will be removed in 0.6.0.
    """

    def __init__(self, entity_extractor: EntityExtractor) -> None:
        _warn_adapter("SyncEntityExtractorAdapter", "AsyncEntityExtractor")
        self._entity_extractor = entity_extractor

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._entity_extractor.extract, text)


class SyncExporterAdapter(AsyncExporter):
    """Serialize exports on the loop thread so concurrent writes cannot interleave.

    .. deprecated:: 0.5.0
        The blocking contracts and their adapters will be removed in 0.6.0.
    """

    def __init__(self, exporter: Exporter) -> None:
        _warn_adapter("SyncExporterAdapter", "AsyncExporter")
        self._exporter = exporter

    async def export(self, data: Any, destination: str) -> None:
        self._exporter.export(data, destination)


class SyncStateManagerAdapter(AsyncStateManager):
    """Serialize state mutations on the loop thread to avoid lost updates.

    .. deprecated:: 0.5.0
        The blocking contracts and their adapters will be removed in 0.6.0.
    """

    def __init__(self, state_manager: StateManager) -> None:
        _warn_adapter("SyncStateManagerAdapter", "AsyncStateManager")
        self._state_manager = state_manager

    async def load_processed_ids(self) -> set[str]:
        return self._state_manager.load_processed_ids()

    async def mark_processed(self, record_id: str) -> None:
        self._state_manager.mark_processed(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return self._state_manager.load_metadata()

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        self._state_manager.save_metadata(metadata)
