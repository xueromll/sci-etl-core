"""One test per rule of ``docs/guide/run-semantics.md``, named after the rule.

A change to a rule changes its test here, so the diff shows which guarantee
moved.
"""

from __future__ import annotations

import pytest
from harness import State, build, records

from sci_etl_core.exceptions import (
    EmbeddingError,
    MalformedResponseError,
    PipelineAborted,
    PipelineInterrupted,
    UpstreamError,
)
from sci_etl_core.models import RawRecord
from sci_etl_core.observability import RecordFinished
from sci_etl_core.signals import ShutdownSignal


class FailingMemory:
    async def ingest(self, record: RawRecord, text: str) -> int:
        raise EmbeddingError("embedding service unavailable")


@pytest.mark.asyncio
async def test_r1_offset_waits_for_settled_page():
    run = build(records("a", "b", "c", "d", "e", "f"), failing={"c"})

    assert await run.run(page_size=2, total_limit=10) == 5

    assert run.listing.requests == [0, 2, 4, 6]
    assert run.state.saved_offsets == [2, 2, 2]
    assert run.state.metadata.last_start_index == 2


@pytest.mark.asyncio
async def test_r2_total_limit_is_exact_and_releases_failed_slots():
    run = build(records("bad", "a", "b", "c"), failing={"bad"}, max_concurrency=1)

    assert await run.run(page_size=4, total_limit=2) == 2

    assert run.entities.extracted == ["a", "b"]
    assert run.state.marked == ["a", "b"]
    assert run.state.metadata.last_start_index == 0


@pytest.mark.asyncio
async def test_r3_irrelevant_record_is_marked_processed_at_once():
    run = build(records("a", "b"), irrelevant={"a"})

    assert await run.run(page_size=2, total_limit=10) == 1

    assert run.state.marked == ["a", "b"]
    assert run.entities.extracted == ["b"]
    assert run.exporter.exported == [{"record": "b"}]


@pytest.mark.asyncio
async def test_r4_memory_fault_is_logged_and_counted_and_the_record_still_exports():
    run = build(records("a"), memory_ingestor=FailingMemory())

    assert await run.run(page_size=1, total_limit=1) == 1

    assert run.exporter.exported == [{"record": "a"}]
    assert run.state.marked == ["a"]
    assert run.pipeline.last_run_metrics.memory_faults == 1
    assert any(line.startswith("Memory ingest failed for a:") for line in run.logged)


@pytest.mark.asyncio
async def test_r5_two_stalled_pages_abort_the_run():
    run = build(records("a", "b", "c", "d", "e", "f"), failing={"a", "b", "c", "d"})

    with pytest.raises(PipelineAborted, match="Records kept failing") as aborted:
        await run.run(page_size=2, total_limit=10)

    assert aborted.value.partial_count == 0
    assert run.listing.requests == [0, 2]
    assert isinstance(aborted.value.__cause__, Exception)


@pytest.mark.asyncio
async def test_r5_a_single_stalled_page_is_tolerated_when_a_later_page_processes():
    run = build(records("a", "b", "c", "d", "e", "f"), failing={"a", "b"})

    assert await run.run(page_size=2, total_limit=10) == 4

    assert run.listing.requests == [0, 2, 4, 6]


@pytest.mark.asyncio
async def test_r6_stalled_page_before_the_listing_ends_aborts_the_run():
    run = build(records("a", "b", "c", "d"), failing={"c", "d"})

    with pytest.raises(PipelineAborted, match="Records kept failing") as aborted:
        await run.run(page_size=2, total_limit=10)

    assert aborted.value.partial_count == 2
    assert run.listing.requests == [0, 2, 4]
    assert run.pipeline.last_run_metrics.outcome == "aborted"


@pytest.mark.asyncio
async def test_r7_empty_listing_ends_the_run_cleanly():
    run = build(records("a", "b", "c"))

    assert await run.run(page_size=2, total_limit=10) == 3

    assert run.listing.requests == [0, 2, 3]
    assert run.pipeline.last_run_metrics.outcome == "completed"
    assert run.state.metadata.last_start_index == 3


@pytest.mark.asyncio
async def test_r7_a_missing_payload_is_not_the_end_of_the_listing():
    run = build(records("a", "b", "c", "d"))
    run.listing.missing_payloads.add(2)

    with pytest.raises(PipelineAborted, match="no payload") as aborted:
        await run.run(page_size=2, total_limit=10)

    assert aborted.value.partial_count == 2


@pytest.mark.asyncio
async def test_r8_page_of_processed_records_is_not_the_end():
    run = build(records("a", "b", "c", "d"), state=State(processed={"a", "b"}))

    assert await run.run(page_size=2, total_limit=10) == 2

    assert run.listing.requests == [0, 2, 4]
    assert run.relevance.asked == ["c", "d"]
    assert run.state.metadata.last_start_index == 4


@pytest.mark.asyncio
async def test_r9_shutdown_finishes_in_flight_records_and_raises_interrupted():
    shutdown = ShutdownSignal(signals=())
    run = build(records("a", "b", "c", "d"), max_concurrency=1, shutdown=shutdown)

    async def request_during_first_record(record_id: str) -> None:
        if record_id == "a":
            shutdown.request()

    run.entities.before_extract = request_during_first_record

    with pytest.raises(PipelineInterrupted) as interrupted:
        await run.run(page_size=4, total_limit=10)

    assert interrupted.value.partial_count == 1
    assert run.state.marked == ["a"]
    assert run.state.metadata.last_start_index == 0
    assert run.state.flushes == 1
    assert run.pipeline.last_run_metrics.outcome == "interrupted"


@pytest.mark.asyncio
async def test_r10_state_is_flushed_when_a_run_completes():
    run = build(records("a"))

    await run.run(page_size=1, total_limit=10)

    assert run.state.flushes == 1


@pytest.mark.asyncio
async def test_r10_a_flush_fault_never_hides_the_original_error():
    run = build(records("a", "b"))
    run.listing.search_faults[0] = UpstreamError("source unreachable")
    run.state.flush_fault = OSError("disk full")

    with pytest.raises(PipelineAborted, match="Listing fetch failed"):
        await run.run(page_size=2, total_limit=10)

    assert run.state.flushes == 1
    assert any(line.startswith("State flush failed: OSError('disk full')") for line in run.logged)


@pytest.mark.parametrize("record_id", ["", "   "])
@pytest.mark.asyncio
async def test_r11_blank_record_id_is_skipped_and_reported(record_id):
    run = build([RawRecord(record_id=record_id, title="untracked", abstract="abstract"), *records("a")])

    assert await run.run(page_size=2, total_limit=10) == 1

    assert run.relevance.asked == ["a"]
    assert run.state.marked == ["a"]
    assert any("no record_id" in line and "'untracked'" in line for line in run.logged)
    skipped = [event for event in run.events if isinstance(event, RecordFinished) and event.outcome == "skipped"]
    assert [event.title for event in skipped] == ["untracked"]


@pytest.mark.asyncio
async def test_r12_no_wait_after_the_page_that_reaches_total_limit():
    run = build(records("a", "b", "c", "d", "e", "f"))

    assert await run.run(page_size=2, total_limit=4, sleep_between=5.0) == 4

    assert run.listing.requests == [0, 2]
    assert run.sleep.waits == [5.0]


@pytest.mark.asyncio
async def test_r13_listing_fetch_fault_aborts_with_the_partial_count():
    run = build(records("a", "b", "c", "d"))
    run.listing.search_faults[2] = UpstreamError("source unreachable")

    with pytest.raises(PipelineAborted, match="Listing fetch failed") as aborted:
        await run.run(page_size=2, total_limit=10)

    assert aborted.value.partial_count == 2
    assert isinstance(aborted.value.__cause__, UpstreamError)


@pytest.mark.asyncio
async def test_r13_listing_parse_fault_aborts_with_the_partial_count():
    run = build(records("a", "b", "c", "d"))
    run.listing.malformed_pages.add(2)

    with pytest.raises(PipelineAborted, match="Listing payload was malformed") as aborted:
        await run.run(page_size=2, total_limit=10)

    assert aborted.value.partial_count == 2
    assert isinstance(aborted.value.__cause__, MalformedResponseError)


@pytest.mark.asyncio
async def test_r14_newest_first_run_rescans_from_zero_until_the_saved_head_is_found():
    listed = records("r0", "r1", "r2", "r3", "r4", "r5")
    first = build(listed)
    assert await first.run(page_size=2, total_limit=10, newest_first=True) == 6
    assert first.state.metadata.head_ids == ["r0", "r1"]

    second = build([*records("n0"), *listed], state=first.state)
    first.state.marked.clear()

    assert await second.run(page_size=2, total_limit=10, newest_first=True) == 1

    assert second.listing.requests == [0, 2, 5, 7]
    assert first.state.marked == ["n0"]
    assert any("1 new listing entries since the last run" in line for line in second.logged)


@pytest.mark.asyncio
async def test_characterization_capped_listing_pins_every_later_run_at_the_cap():
    run = build(records("a", "b", "c", "d", "e", "f"))
    run.listing.cap = 4

    assert await run.run(page_size=2, total_limit=10) == 4
    assert run.listing.requests == [0, 2, 4]
    assert run.state.metadata.last_start_index == 4
    assert run.pipeline.last_run_metrics.outcome == "completed"

    run.listing.listed.insert(0, *records("new"))
    run.listing.requests.clear()

    assert await run.run(page_size=2, total_limit=10) == 0
    assert run.listing.requests == [4]
    assert "new" not in run.relevance.asked
