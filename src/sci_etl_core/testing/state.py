"""The contract suite for state managers.

Subclass :class:`StateManagerContract` in a test module under a name pytest
collects, such as ``TestMyStateManager``, and give it a ``make_state_manager``
fixture:

```python
import pytest

from sci_etl_core.testing import StateManagerContract

from my_package import MyStateManager


class TestMyStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: MyStateManager(tmp_path / "state.db")
```

The tests are plain functions that run each scenario with :func:`asyncio.run`,
so pytest-asyncio is not needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest

from sci_etl_core.exceptions import SciEtlError
from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager, Forgetting


@asynccontextmanager
async def _session(make_state_manager: Callable[[], AsyncStateManager]) -> AsyncIterator[AsyncStateManager]:
    manager = make_state_manager()
    try:
        yield manager
    finally:
        await manager.flush()
        await _close(manager)


async def _close(manager: AsyncStateManager) -> None:
    aclose = getattr(manager, "aclose", None)
    if aclose is not None:
        await aclose()


def _tracks_failures(manager: AsyncStateManager) -> bool:
    return type(manager).record_failure is not AsyncStateManager.record_failure


class StateManagerContract:
    """Tests every :class:`~sci_etl_core.state.async_base.AsyncStateManager` must pass.

    A subclass provides the ``make_state_manager`` fixture. It returns a
    callable that takes no argument and returns a new state manager over the
    same storage each time it is called, as each run of a pipeline opens it,
    and the storage starts empty in every test. The suite calls it inside a
    running event loop, and ends each instance as a run ends: it awaits
    ``flush()``, then ``aclose()`` when the instance has one. A state manager
    that keeps its state in memory returns the same instance on every call.

    A subclass may also override the ``write_newer_schema`` fixture to check
    that state from a newer release is refused.

    Some tests check an optional capability and skip when the implementation
    lacks it: failed attempts, when ``record_failure`` keeps the default that
    tracks nothing; ``forget``, when the state manager is not
    :class:`~sci_etl_core.state.async_base.Forgetting`; reuse after
    ``aclose()``, when it has no ``aclose``; and the schema-version test,
    when ``write_newer_schema`` returns ``None``.
    """

    @pytest.fixture
    def write_newer_schema(self) -> Callable[[], None] | None:
        """Return a callable that writes state from a newer schema version into the storage, or ``None``.

        The suite calls it before it creates a state manager. The default
        returns ``None``, which skips the schema-version test; override it
        when the implementation records a schema version.
        """
        return None

    def test_new_storage_is_empty(self, make_state_manager: Callable[[], AsyncStateManager]) -> None:
        """A new storage holds no processed id, no failed attempt, and default metadata."""

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                assert await manager.load_processed_ids() == set()
                assert await manager.failure_counts() == {}
                assert await manager.load_metadata() == PipelineMetadata()

        asyncio.run(scenario())

    def test_processed_ids_persist_across_instances(self, make_state_manager: Callable[[], AsyncStateManager]) -> None:
        """Marked ids are loaded by the next instance, and marking an id twice keeps it once."""

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                await manager.mark_processed("record-1")
                await manager.mark_processed("record-2")
                await manager.mark_processed("record-1")
            async with _session(make_state_manager) as manager:
                assert await manager.load_processed_ids() == {"record-1", "record-2"}

        asyncio.run(scenario())

    def test_concurrent_marks_are_all_kept(self, make_state_manager: Callable[[], AsyncStateManager]) -> None:
        """Ids marked concurrently, as the pipeline marks a page's records, are all kept."""
        record_ids = {f"record-{index}" for index in range(20)}

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                await asyncio.gather(*(manager.mark_processed(record_id) for record_id in record_ids))
            async with _session(make_state_manager) as manager:
                assert await manager.load_processed_ids() == record_ids

        asyncio.run(scenario())

    def test_saved_metadata_resumes_in_a_new_instance(
        self, make_state_manager: Callable[[], AsyncStateManager]
    ) -> None:
        """The next instance loads the saved cursor and listing head, stamped with a run time."""
        saved = PipelineMetadata(
            cursor="cursor-2", truncated=True, head_ids=["head-1", "head-2"], head_offset=3, tail_ids=["tail-1"]
        )

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                await manager.save_metadata(saved)
            async with _session(make_state_manager) as manager:
                loaded = await manager.load_metadata()
                assert loaded.cursor == "cursor-2"
                assert loaded.truncated is True
                assert loaded.head_ids == ["head-1", "head-2"]
                assert loaded.head_offset == 3
                assert loaded.tail_ids == ["tail-1"]
                assert loaded.last_run_at is not None
                await manager.save_metadata(PipelineMetadata())
            async with _session(make_state_manager) as manager:
                reset = await manager.load_metadata()
                assert reset.cursor is None
                assert reset.truncated is False

        asyncio.run(scenario())

    def test_failed_attempts_are_counted_across_instances(
        self, make_state_manager: Callable[[], AsyncStateManager]
    ) -> None:
        """``record_failure`` returns the attempts so far, and the next instance loads them."""

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                if not _tracks_failures(manager):
                    pytest.skip(f"{type(manager).__name__} does not track failed attempts")
                assert await manager.record_failure("record-1", "first fault") == 1
                assert await manager.record_failure("record-1", "second fault") == 2
                assert await manager.record_failure("record-2", "fault") == 1
            async with _session(make_state_manager) as manager:
                assert await manager.failure_counts() == {"record-1": 2, "record-2": 1}

        asyncio.run(scenario())

    def test_mark_processed_clears_failed_attempts(self, make_state_manager: Callable[[], AsyncStateManager]) -> None:
        """Marking a record processed clears its failed attempts and leaves other records' attempts."""

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                if not _tracks_failures(manager):
                    pytest.skip(f"{type(manager).__name__} does not track failed attempts")
                await manager.record_failure("record-1", "fault")
                await manager.record_failure("record-1", "fault")
                await manager.record_failure("record-2", "fault")
                await manager.mark_processed("record-1")
                assert await manager.failure_counts() == {"record-2": 1}
            async with _session(make_state_manager) as manager:
                assert await manager.failure_counts() == {"record-2": 1}

        asyncio.run(scenario())

    def test_forget_clears_processed_marks_and_failed_attempts(
        self, make_state_manager: Callable[[], AsyncStateManager]
    ) -> None:
        """``forget`` clears the given ids' marks and attempts, ignores unknown ids, and keeps the cursor."""

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                if not isinstance(manager, Forgetting):
                    pytest.skip(f"{type(manager).__name__} does not implement Forgetting")
                await manager.mark_processed("record-1")
                await manager.mark_processed("record-2")
                await manager.record_failure("record-3", "fault")
                await manager.save_metadata(PipelineMetadata(cursor="cursor-2"))
                await manager.forget([])
                await manager.forget(["record-1", "record-3", "unknown", ""])
            async with _session(make_state_manager) as manager:
                assert await manager.load_processed_ids() == {"record-2"}
                assert await manager.failure_counts() == {}
                assert (await manager.load_metadata()).cursor == "cursor-2"

        asyncio.run(scenario())

    def test_a_newer_schema_version_is_refused(
        self, make_state_manager: Callable[[], AsyncStateManager], write_newer_schema: Callable[[], None] | None
    ) -> None:
        """State from a newer schema version raises a ``SciEtlError`` on load and on save."""
        if write_newer_schema is None:
            pytest.skip("write_newer_schema is not provided")
        write_newer_schema()

        async def scenario() -> None:
            manager = make_state_manager()
            with pytest.raises(SciEtlError):
                await manager.load_metadata()
            with pytest.raises(SciEtlError):
                await manager.save_metadata(PipelineMetadata(cursor="cursor-1"))
            await _close(manager)

        asyncio.run(scenario())

    def test_aclose_then_reuse(self, make_state_manager: Callable[[], AsyncStateManager]) -> None:
        """A closed state manager keeps working, with the state it held before ``aclose()``."""

        async def scenario() -> None:
            async with _session(make_state_manager) as manager:
                aclose = getattr(manager, "aclose", None)
                if aclose is None:
                    pytest.skip(f"{type(manager).__name__} has no aclose")
                await manager.mark_processed("record-1")
                await aclose()
                await manager.mark_processed("record-2")
                assert await manager.load_processed_ids() == {"record-1", "record-2"}

        asyncio.run(scenario())
