"""Edges of the 0.5 page contract that the rule tests do not reach."""

from __future__ import annotations

import pytest
from harness import State, build, records

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.observability import PageFetched, RunStarted


@pytest.mark.asyncio
async def test_newest_first_stops_on_a_last_page_without_a_next_cursor():
    run = build(records("a", "b", "c"))
    run.listing.ends_on_last_page = True

    assert await run.run(page_size=2, total_limit=10, newest_first=True) == 3

    assert run.listing.requests == [0, 2]
    assert run.state.metadata.cursor == "3"
    assert run.state.metadata.head_ids == ["a", "b"]


@pytest.mark.asyncio
async def test_newest_first_probe_past_a_listing_that_ends_early_stops_at_the_head():
    listed = records(*(f"r{number}" for number in range(8)))
    first = build(listed)
    assert await first.run(page_size=2, total_limit=10, newest_first=True) == 8

    shrunk = build([*records("n0"), *listed[:3]], state=first.state)
    shrunk.listing.ends_on_last_page = True

    assert await shrunk.run(page_size=2, total_limit=10, newest_first=True) == 1
    assert shrunk.listing.requests == [0, 2]


@pytest.mark.asyncio
async def test_newest_first_truncation_resets_the_backlog_and_keeps_the_head():
    run = build(records("a", "b", "c", "d", "e"), state=State(metadata=PipelineMetadata(cursor="4")))
    run.listing.cap = 4

    assert await run.run(page_size=2, total_limit=10, newest_first=True) == 4

    assert run.state.metadata.cursor is None
    assert run.state.metadata.truncated is True
    assert run.state.metadata.head_ids == ["a", "b"]


@pytest.mark.asyncio
async def test_newest_first_stale_cursor_rescans_from_zero_and_rebuilds_the_head():
    saved = PipelineMetadata(cursor="4", head_ids=["x"], head_offset=3, tail_ids=["y"])
    run = build(records("a", "b", "c"), state=State(processed={"a"}, metadata=saved))
    run.listing.stale.add("2")

    assert await run.run(page_size=2, total_limit=10, newest_first=True) == 2

    assert run.listing.cursors == [None, "2", None, "2", "3"]
    assert run.state.metadata.head_ids == ["a", "b"]
    assert run.state.metadata.cursor == "3"
    assert run.state.metadata.tail_ids == ["c"]


@pytest.mark.asyncio
async def test_an_offset_listing_with_a_saved_cursor_that_is_not_an_offset_reports_no_offset():
    run = build(records("a", "b"), state=State(metadata=PipelineMetadata(cursor="token")))
    run.listing.stale.add("token")

    assert await run.run(page_size=2, total_limit=10) == 2

    started = next(event for event in run.events if isinstance(event, RunStarted))
    assert (started.cursor, started.start_index) == ("token", None)
    assert [event.offset for event in run.events if isinstance(event, PageFetched)] == [0, 2]


@pytest.mark.asyncio
async def test_a_quarantined_record_listed_twice_is_counted_and_logged_once():
    state = State()
    state.failures = {"q": 5}
    listing = [*records("q", "a"), *records("q", "b")]
    run = build(listing, state=state)

    assert await run.run(page_size=2, total_limit=10) == 2

    assert run.pipeline.last_run_metrics.quarantined == 1
    assert sum("q skipped: quarantined" in line for line in run.logged) == 1


@pytest.mark.asyncio
async def test_start_index_above_zero_resumes_an_offset_listing_there():
    run = build(records("a", "b", "c", "d"))

    assert await run.run(page_size=2, total_limit=10, start_index=2) == 2

    assert run.listing.cursors == ["2", "4"]
