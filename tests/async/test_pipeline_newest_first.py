from __future__ import annotations

import asyncio
import copy

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sci_etl_core._listing_head import HEAD_ID_LIMIT
from sci_etl_core.exceptions import LLMError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.state.async_base import AsyncStateManager


class ShiftingListing(AsyncExtractor):
    """A newest-first listing that new submissions push down."""

    def __init__(self, size: int) -> None:
        self._next_id = 0
        self.entries: list[str] = []
        self.requested_offsets: list[int] = []
        self.publish(size)

    def publish(self, count: int) -> None:
        fresh = [f"r{self._next_id + number}" for number in range(count)]
        self._next_id += count
        self.entries = list(reversed(fresh)) + self.entries

    async def search(self, query: str, max_results: int, start_index: int) -> bytes:
        self.requested_offsets.append(start_index)
        return ",".join(self.entries[start_index : start_index + max_results]).encode() or b"-"

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        ids = [] if raw_listing == b"-" else raw_listing.decode().split(",")
        records = [RawRecord(record_id, record_id, "abstract") for record_id in ids if record_id not in seen_ids]
        return records, len(ids)

    async def fetch_full_text(self, record: RawRecord) -> str:
        return record.record_id


class MemoryState(AsyncStateManager):
    def __init__(self) -> None:
        self.processed: set[str] = set()
        self.metadata = PipelineMetadata()

    async def load_processed_ids(self) -> set[str]:
        return set(self.processed)

    async def mark_processed(self, record_id: str) -> None:
        self.processed.add(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return copy.deepcopy(self.metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        self.metadata = copy.deepcopy(metadata)


class FlakyExtraction(AsyncEntityExtractor):
    def __init__(self) -> None:
        self.failing: set[str] = set()

    async def extract(self, text: str | bytes) -> list[dict]:
        if text in self.failing:
            raise LLMError("transient")
        return [{"id": text}]


class AlwaysRelevant(AsyncRelevanceFilter):
    async def is_relevant(self, record: RawRecord) -> bool:
        return True


class DiscardingExporter(AsyncExporter):
    async def export(self, data, destination: str) -> None:
        return None


def _pipeline(listing, state, extraction=None, logger=None):
    return AsyncETLPipeline(
        extractor=listing,
        relevance_filter=AlwaysRelevant(),
        entity_extractor=extraction or FlakyExtraction(),
        exporter=DiscardingExporter(),
        state_manager=state,
        destination="out",
        max_concurrency=4,
        logger=logger,
    )


async def _run(listing, state, extraction=None, total_limit=10_000, page_size=10, logger=None):
    listing.requested_offsets.clear()
    return await _pipeline(listing, state, extraction, logger).run(
        query="q", page_size=page_size, total_limit=total_limit, newest_first=True
    )


class TestNewestFirstResume:
    @pytest.mark.asyncio
    async def test_the_first_run_scans_from_zero_and_saves_the_head(self):
        listing, state = ShiftingListing(25), MemoryState()
        assert await _run(listing, state) == 25
        assert listing.requested_offsets == [0, 10, 20, 25]
        assert state.metadata.head_ids == listing.entries[:10]
        assert state.metadata.head_offset == 0
        assert state.metadata.last_start_index == 25

    @pytest.mark.asyncio
    async def test_new_submissions_are_picked_up_without_listing_the_middle_again(self):
        listing, state = ShiftingListing(95), MemoryState()
        await _run(listing, state)
        listing.publish(3)
        lines: list[str] = []
        assert await _run(listing, state, logger=lines.append) == 3
        assert listing.requested_offsets == [0, 10, 88, 98]
        assert state.processed == set(listing.entries)
        assert "3 new listing entries since the last run; resuming at 88" in lines
        assert state.metadata.head_ids == listing.entries[:10]
        assert state.metadata.last_start_index == 98

    @pytest.mark.asyncio
    async def test_a_backlog_left_by_a_limit_resumes_below_the_new_submissions(self):
        listing, state = ShiftingListing(40), MemoryState()
        assert await _run(listing, state, total_limit=20) == 20
        assert state.metadata.last_start_index == 20
        listing.publish(12)
        assert await _run(listing, state) == 32
        assert listing.requested_offsets == [0, 10, 20, 30, 40, 50, 52]
        assert state.processed == set(listing.entries)

    @pytest.mark.asyncio
    async def test_a_head_record_that_failed_anchors_the_next_scan_on_its_own_page(self):
        listing, state = ShiftingListing(30), MemoryState()
        await _run(listing, state)
        listing.publish(5)
        extraction = FlakyExtraction()
        extraction.failing = {listing.entries[1]}
        assert await _run(listing, state, extraction) == 4
        assert listing.requested_offsets == [0, 10, 25, 35]
        saved = state.metadata
        assert saved.head_ids == listing.entries[:10]
        assert saved.head_offset == 0
        assert saved.last_start_index == 35
        assert saved.tail_ids == listing.entries[25:35]
        listing.publish(2)
        assert await _run(listing, state) == 3
        assert listing.requested_offsets == [0, 10, 27, 37]
        assert state.processed == set(listing.entries)
        assert state.metadata.head_ids == listing.entries[:10]
        assert state.metadata.head_offset == 0

    @pytest.mark.asyncio
    async def test_a_run_stopped_by_its_limit_before_the_anchor_keeps_the_saved_position(self):
        listing, state = ShiftingListing(30), MemoryState()
        await _run(listing, state)
        before = copy.deepcopy(state.metadata)
        listing.publish(15)
        assert await _run(listing, state, total_limit=10) == 10
        assert state.metadata.head_ids == before.head_ids
        assert state.metadata.head_offset == before.head_offset
        assert state.metadata.last_start_index == before.last_start_index
        assert await _run(listing, state) == 5
        assert state.processed == set(listing.entries)

    @pytest.mark.asyncio
    async def test_when_the_saved_head_is_gone_the_whole_listing_is_rescanned(self):
        listing, state = ShiftingListing(30), MemoryState()
        await _run(listing, state)
        state.metadata.head_ids = ["withdrawn"]
        lines: list[str] = []
        assert await _run(listing, state, logger=lines.append) == 0
        assert listing.requested_offsets == [0, 10, 20, 30]
        assert "Listing ended before the records last seen at its head; rescanned from offset 0" in lines
        assert state.metadata.head_ids == listing.entries[:10]
        assert state.metadata.last_start_index == 30

    @pytest.mark.asyncio
    async def test_a_failure_during_a_rescan_holds_the_saved_offset_at_its_page(self):
        listing, state = ShiftingListing(30), MemoryState()
        extraction = FlakyExtraction()
        extraction.failing = {listing.entries[14]}
        assert await _run(listing, state, extraction) == 29
        assert state.metadata.last_start_index == 10

    @pytest.mark.asyncio
    async def test_a_withdrawn_entry_moves_the_backlog_up(self):
        listing, state = ShiftingListing(40), MemoryState()
        await _run(listing, state, total_limit=20)
        listing.entries.pop(3)
        assert await _run(listing, state) == 20
        assert set(listing.entries) <= state.processed

    @pytest.mark.asyncio
    async def test_only_a_limited_number_of_head_ids_is_saved(self):
        listing, state = ShiftingListing(60), MemoryState()
        await _run(listing, state, page_size=50)
        assert len(state.metadata.head_ids) == HEAD_ID_LIMIT

    @pytest.mark.asyncio
    async def test_a_failed_record_after_the_anchor_on_its_page_is_still_revisited(self):
        listing, state = ShiftingListing(4), MemoryState()
        assert await _run(listing, state, total_limit=1, page_size=2) == 1
        extraction = FlakyExtraction()
        extraction.failing = {listing.entries[1]}
        assert await _run(listing, state, extraction, total_limit=2, page_size=2) == 2
        listing.publish(1)
        assert await _run(listing, state, total_limit=1, page_size=2) == 1
        await _run(listing, state, page_size=2)
        assert set(listing.entries) <= state.processed

    @pytest.mark.asyncio
    async def test_when_the_tail_has_moved_the_run_pages_on_from_the_head(self):
        listing, state = ShiftingListing(60), MemoryState()
        await _run(listing, state, total_limit=40)
        for _ in range(12):
            listing.entries.pop(15)
        lines: list[str] = []
        assert await _run(listing, state, logger=lines.append) == 20
        assert listing.requested_offsets == [0, 30, 10, 20, 30, 40, 48]
        assert "Records last seen before the saved offset have moved; paging on from 10" in lines
        assert set(listing.entries) <= state.processed

    @pytest.mark.asyncio
    async def test_when_the_listing_ends_at_the_probe_the_run_pages_on_from_the_head(self):
        listing, state = ShiftingListing(50), MemoryState()
        await _run(listing, state, total_limit=40)
        del listing.entries[10:40]
        lines: list[str] = []
        assert await _run(listing, state, logger=lines.append) == 10
        assert listing.requested_offsets == [0, 30, 10, 20]
        assert "Records last seen before the saved offset have moved; paging on from 10" in lines

    @pytest.mark.asyncio
    async def test_a_failure_on_the_probe_page_holds_the_offset_there(self):
        listing, state = ShiftingListing(60), MemoryState()
        await _run(listing, state, total_limit=40)
        listing.entries.pop(15)
        extraction = FlakyExtraction()
        extraction.failing = {listing.entries[39]}
        assert await _run(listing, state, extraction) == 19
        assert listing.requested_offsets == [0, 30, 40, 50, 59]
        assert state.metadata.last_start_index == 30
        assert state.metadata.tail_ids == []
        assert await _run(listing, state) == 1
        assert listing.requested_offsets == [0, 10, 20, 30, 40, 50, 59]
        assert set(listing.entries) <= state.processed

    @pytest.mark.asyncio
    async def test_metadata_without_tail_ids_pages_on_from_the_head(self):
        listing, state = ShiftingListing(40), MemoryState()
        await _run(listing, state, total_limit=30)
        state.metadata.tail_ids = []
        assert await _run(listing, state) == 10
        assert listing.requested_offsets == [0, 10, 20, 30, 40]

    @pytest.mark.asyncio
    async def test_start_index_cannot_be_combined_with_newest_first(self):
        listing, state = ShiftingListing(1), MemoryState()
        with pytest.raises(ValueError, match="cannot be combined"):
            await _pipeline(listing, state).run(query="q", start_index=0, newest_first=True)


class TestNewestFirstProperties:
    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        initial=st.integers(min_value=0, max_value=45),
        runs=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=25),
                st.integers(min_value=1, max_value=40),
                st.sets(st.integers(min_value=0, max_value=60), max_size=3),
                st.integers(min_value=0, max_value=4),
            ),
            max_size=5,
        ),
        page_size=st.integers(min_value=1, max_value=12),
    )
    def test_every_record_is_eventually_processed_and_nothing_twice(self, initial, runs, page_size):
        asyncio.run(self._scenario(initial, runs, page_size))

    @staticmethod
    async def _scenario(initial, runs, page_size):
        listing, state = ShiftingListing(initial), MemoryState()
        marked: list[str] = []
        original_mark = state.mark_processed

        async def recording_mark(record_id: str) -> None:
            marked.append(record_id)
            await original_mark(record_id)

        state.mark_processed = recording_mark
        for published, limit, failing_positions, withdrawn in runs:
            listing.publish(published)
            for _ in range(min(withdrawn, len(listing.entries))):
                listing.entries.pop(len(listing.entries) // 2)
            extraction = FlakyExtraction()
            extraction.failing = {
                listing.entries[position] for position in failing_positions if position < len(listing.entries)
            }
            try:
                await _run(listing, state, extraction, total_limit=limit, page_size=page_size)
            except Exception as error:
                assert type(error).__name__ == "PipelineAborted"
        await _run(listing, state, page_size=page_size)
        assert set(listing.entries) <= state.processed
        assert len(marked) == len(set(marked))
