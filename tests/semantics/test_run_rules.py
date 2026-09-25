"""One test per rule of ``docs/guide/run-semantics.md``, named after the rule.

A change to a rule changes its test here, so the diff shows which guarantee
moved.
"""

from __future__ import annotations

import pytest
from harness import OpaqueListing, State, build, records

from sci_etl_core.exceptions import (
    EmbeddingError,
    MalformedResponseError,
    PipelineAborted,
    PipelineInterrupted,
    UpstreamError,
)
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.observability import PageFetched, RecordFinished
from sci_etl_core.signals import ShutdownSignal


class FailingMemory:
    async def ingest(self, record: RawRecord, text: str) -> int:
        raise EmbeddingError("embedding service unavailable")


@pytest.mark.asyncio
async def test_r1_cursor_waits_for_settled_page():
    run = build(records("a", "b", "c", "d", "e", "f"), failing={"c"})

    assert await run.run(page_size=2, total_limit=10) == 5

    assert run.listing.requests == [0, 2, 4, 6]
    assert run.state.saved_cursors == ["2", "2", "2", "2"]
    assert run.state.metadata.cursor == "2"


@pytest.mark.asyncio
async def test_r2_total_limit_is_exact_and_releases_failed_slots():
    run = build(records("bad", "a", "b", "c"), failing={"bad"}, max_concurrency=1)

    assert await run.run(page_size=4, total_limit=2) == 2

    assert run.entities.extracted == ["a", "b"]
    assert run.state.marked == ["a", "b"]
    assert run.state.metadata.cursor is None


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
async def test_r6_stalled_last_page_without_a_next_cursor_aborts_before_saving_the_end():
    listing = OpaqueListing(records("a", "b", "c", "d"))
    run = build([], failing={"c", "d"}, listing=listing, state=State(metadata=PipelineMetadata(truncated=True)))

    with pytest.raises(PipelineAborted, match="Records kept failing"):
        await run.run(page_size=2, total_limit=10)

    assert listing.cursors == [None, "token-2"]
    assert run.state.metadata.cursor == "token-2"
    assert run.state.metadata.truncated is True


@pytest.mark.asyncio
async def test_r7_empty_page_ends_the_run_and_an_offset_listing_saves_the_offset_past_the_last_entry():
    run = build(records("a", "b", "c"))

    assert await run.run(page_size=2, total_limit=10) == 3

    assert run.listing.requests == [0, 2, 3]
    assert run.pipeline.last_run_metrics.outcome == "completed"
    assert run.state.metadata.cursor == "3"


@pytest.mark.asyncio
async def test_r7_page_without_a_next_cursor_ends_the_run_and_an_opaque_listing_saves_no_cursor():
    listing = OpaqueListing(records("a", "b", "c"))
    run = build([], listing=listing)

    assert await run.run(page_size=2, total_limit=10) == 3

    assert listing.cursors == [None, "token-2"]
    assert run.state.saved_cursors == ["token-2", None]
    assert run.sleep.waits == [1.0]
    assert run.pipeline.last_run_metrics.outcome == "completed"


@pytest.mark.asyncio
async def test_r8_page_of_processed_records_is_not_the_end():
    run = build(records("a", "b", "c", "d"), state=State(processed={"a", "b"}))

    assert await run.run(page_size=2, total_limit=10) == 2

    assert run.listing.requests == [0, 2, 4]
    assert run.relevance.asked == ["c", "d"]
    assert run.state.metadata.cursor == "4"


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
    assert run.state.metadata.cursor is None
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
    run.listing.fetch_faults[0] = UpstreamError("source unreachable")
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
    run.listing.fetch_faults[2] = UpstreamError("source unreachable")

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
    assert second.listing.cursors == [None, "2", "5", "7"]
    assert first.state.marked == ["n0"]
    assert any("1 new listing entries since the last run" in line for line in second.logged)


@pytest.mark.asyncio
async def test_r15_run_after_a_capped_run_pages_from_the_first_page_again():
    run = build(records("a", "b", "c", "d", "e", "f"))
    run.listing.cap = 4

    assert await run.run(page_size=2, total_limit=10) == 4
    assert run.listing.requests == [0, 2]
    assert run.state.metadata.cursor is None
    assert run.state.metadata.truncated is True
    assert run.pipeline.last_run_metrics.listing_truncated is True
    assert run.pipeline.last_run_metrics.outcome == "completed"
    fetched = [event for event in run.events if isinstance(event, PageFetched)]
    assert [event.truncated for event in fetched] == [False, True]
    assert sum("result cap" in line for line in run.logged) == 1

    run.listing.listed.insert(0, *records("new"))
    run.listing.requests.clear()

    assert await run.run(page_size=2, total_limit=10) == 1
    assert run.listing.requests == [0, 2]
    assert "new" in run.relevance.asked


@pytest.mark.asyncio
async def test_r15_truncated_flag_clears_when_a_later_run_reaches_the_end_without_a_cap():
    run = build(records("a", "b", "c"), state=State(metadata=PipelineMetadata(truncated=True)))

    await run.run(page_size=2, total_limit=10)

    assert run.state.metadata.truncated is False


@pytest.mark.asyncio
async def test_r15_truncated_page_resets_the_cursor_even_when_a_page_did_not_settle():
    run = build(records("a", "b", "c", "d", "e", "f"), failing={"a"})
    run.listing.cap = 4

    assert await run.run(page_size=2, total_limit=10) == 3

    assert run.state.saved_cursors == [None, None]
    assert run.state.metadata.truncated is True


@pytest.mark.asyncio
async def test_r15_truncated_stall_page_aborts_under_r6_without_resetting():
    state = State(metadata=PipelineMetadata(cursor="2"))
    run = build(records("a", "b", "c", "d", "e"), failing={"c", "d"}, state=state)
    run.listing.cap = 4

    with pytest.raises(PipelineAborted, match="Records kept failing"):
        await run.run(page_size=2, total_limit=10)

    assert run.state.metadata.cursor == "2"
    assert run.state.metadata.truncated is False
    assert run.pipeline.last_run_metrics.listing_truncated is True


@pytest.mark.asyncio
async def test_r15_run_that_reaches_total_limit_leaves_the_truncated_flag_unchanged():
    run = build(records("a", "b", "c"), state=State(metadata=PipelineMetadata(truncated=True)))

    await run.run(page_size=1, total_limit=1)

    assert run.state.metadata.truncated is True


@pytest.mark.asyncio
async def test_r16_stale_cursor_restarts_the_listing_from_the_first_page_once():
    listing = OpaqueListing(records("a", "b", "c"))
    listing.stale.add("token-2")
    run = build([], listing=listing, state=State(processed={"a", "b"}, metadata=PipelineMetadata(cursor="token-2")))

    assert await run.run(page_size=2, total_limit=10) == 1

    assert listing.cursors == ["token-2", None, "token-2"]
    assert any("no longer accepts cursor 'token-2'" in line for line in run.logged)


@pytest.mark.asyncio
async def test_r16_a_second_stale_cursor_in_the_same_run_aborts():
    listing = OpaqueListing(records("a", "b", "c"))
    listing.stale.update({"token-2", None})
    run = build([], listing=listing, state=State(metadata=PipelineMetadata(cursor="token-2")))

    with pytest.raises(PipelineAborted, match="rejected the listing cursor again"):
        await run.run(page_size=2, total_limit=10)

    assert listing.cursors == ["token-2", None]


@pytest.mark.parametrize("arguments", [{"newest_first": True}, {"start_index": 5}])
@pytest.mark.asyncio
async def test_r17_offset_arguments_need_an_offset_listing(arguments):
    listing = OpaqueListing(records("a"))
    run = build([], listing=listing)

    with pytest.raises(ValueError, match="needs an OffsetListing extractor"):
        await run.run(page_size=2, total_limit=10, **arguments)

    assert listing.cursors == []


@pytest.mark.asyncio
async def test_r17_start_index_zero_needs_no_offset_listing():
    listing = OpaqueListing(records("a"))
    run = build([], listing=listing, state=State(metadata=PipelineMetadata(cursor="token-9")))

    assert await run.run(page_size=2, total_limit=10, start_index=0) == 1

    assert listing.cursors == [None]


@pytest.mark.asyncio
async def test_r18_failures_commit_from_pages_that_processed_a_record():
    run = build(records("a", "b", "c", "d"), failing={"a"})

    await run.run(page_size=2, total_limit=10)

    assert run.state.failures == {"a": 1}
    assert run.state.errors["a"] == "LLMError: extraction failed for a"


@pytest.mark.asyncio
async def test_r18_stalled_page_failures_commit_once_a_later_page_processes():
    run = build(records("a", "b", "c", "d"), failing={"a", "b"})

    await run.run(page_size=2, total_limit=10)

    assert run.state.failures == {"a": 1, "b": 1}


@pytest.mark.asyncio
async def test_r18_an_outage_run_three_times_commits_no_attempts():
    state = State()
    for _ in range(3):
        run = build(records("a", "b", "c", "d", "e", "f"), failing={"a", "b", "c", "d", "e", "f"}, state=state)
        with pytest.raises(PipelineAborted, match="Records kept failing"):
            await run.run(page_size=2, total_limit=10)

    assert state.failures == {}


@pytest.mark.asyncio
async def test_r18_poison_record_alone_on_the_last_page_aborts_and_commits_nothing():
    state = State(processed={"good"})
    run = build(records("good", "poison"), failing={"poison"}, state=state)

    with pytest.raises(PipelineAborted, match="Records kept failing"):
        await run.run(page_size=2, total_limit=10)

    assert state.failures == {}


@pytest.mark.asyncio
async def test_r18_record_failing_max_attempts_times_is_skipped_as_quarantined_on_a_later_run():
    state = State()
    for attempt in range(3):
        run = build(records("poison", f"good{attempt}"), failing={"poison"}, state=state)
        await run.run(page_size=2, total_limit=10, start_index=0)
    assert state.failures == {"poison": 3}

    run = build(records("poison", "good0", "fresh"), failing={"poison"}, state=state)
    assert await run.run(page_size=3, total_limit=10, start_index=0) == 1

    assert "poison" not in run.relevance.asked
    assert run.pipeline.last_run_metrics.quarantined == 1
    assert run.pipeline.last_run_metrics.failed == 0
    assert run.state.metadata.cursor == "3"
    assert sum("poison skipped: quarantined after 3 failed attempts" in line for line in run.logged) == 1


@pytest.mark.asyncio
async def test_r18_page_of_quarantined_records_does_not_stall():
    state = State(processed={"a"})
    state.failures = {"b": 3, "c": 3, "d": 3}
    run = build(records("a", "b", "c", "d", "e"), state=state)

    assert await run.run(page_size=2, total_limit=10) == 1

    assert run.listing.requests == [0, 2, 4, 5]
    assert run.pipeline.last_run_metrics.quarantined == 3
    assert run.state.metadata.cursor == "5"


@pytest.mark.asyncio
async def test_r18_max_attempts_none_counts_and_quarantines_nothing():
    state = State()
    state.failures = {"a": 9}
    run = build(records("a", "b", "c"), failing={"c"}, state=state)

    assert await run.run(page_size=3, total_limit=10, max_attempts=None) == 2

    assert "a" in run.relevance.asked
    assert state.failures == {}
