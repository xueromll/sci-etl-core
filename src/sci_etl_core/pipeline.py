from __future__ import annotations

import asyncio
from typing import Any, Callable

from sci_etl_core.exporters.base import Exporter
from sci_etl_core.extractors.base import Extractor
from sci_etl_core.llm.extraction import EntityExtractor
from sci_etl_core.llm.relevance import RelevanceFilter
from sci_etl_core.models import RawRecord
from sci_etl_core.state.base import StateManager


class ETLPipeline:
    def __init__(
        self,
        extractor: Extractor,
        relevance_filter: RelevanceFilter,
        entity_extractor: EntityExtractor,
        exporter: Exporter,
        state_manager: StateManager,
        destination: str,
        max_concurrency: int = 6,
        logger: Callable[[str], None] | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._extractor = extractor
        self._relevance_filter = relevance_filter
        self._entity_extractor = entity_extractor
        self._exporter = exporter
        self._state_manager = state_manager
        self._destination = destination
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._log = logger or (lambda _msg: None)
        self._sleep = sleep

    async def run(self, query: str, max_records: int, sleep_between: float) -> int:
        processed_ids = self._state_manager.load_processed_ids()
        metadata = self._state_manager.load_metadata()
        start_index = metadata.last_start_index
        total_processed = 0

        while total_processed < max_records:
            raw_listing = await self._extractor.search(query, max_records, start_index)
            if not raw_listing:
                break

            records, total_in_listing = self._extractor.parse_listing(raw_listing, processed_ids)
            if total_in_listing == 0 or not records:
                break

            results = await asyncio.gather(
                *(self._process_record(record, processed_ids) for record in records),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    self._log(f"Record processing failed: {result}")
                elif result:
                    total_processed += 1

            start_index += total_in_listing
            metadata.last_start_index = start_index
            self._state_manager.save_metadata(metadata)
            await self._sleep(sleep_between)

        return total_processed

    async def _process_record(self, record: RawRecord, processed_ids: set[str]) -> bool:
        async with self._semaphore:
            if not await self._relevance_filter.is_relevant(record):
                self._mark_done(record, processed_ids)
                return False

            text = await self._extractor.fetch_full_text(record)
            entities = await self._entity_extractor.extract(text)
            if entities:
                self._exporter.export(entities, self._destination)

            self._mark_done(record, processed_ids)
            return True

    def _mark_done(self, record: RawRecord, processed_ids: set[str]) -> None:
        if record.record_id:
            self._state_manager.mark_processed(record.record_id)
            processed_ids.add(record.record_id)
