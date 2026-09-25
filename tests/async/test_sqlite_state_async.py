from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import closing

import pytest
import pytest_asyncio

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.sqlite_async import AsyncSqliteStateManager


@pytest_asyncio.fixture
async def manager(tmp_path) -> AsyncIterator[AsyncSqliteStateManager]:
    instance = AsyncSqliteStateManager(tmp_path / "nested" / "state.db")
    yield instance
    await instance.aclose()


def _drop_table(path, table: str) -> None:
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute(f"DROP TABLE {table}")


class TestAsyncSqliteStateManagerContract:
    def test_implements_the_async_state_manager_abc(self, manager):
        assert isinstance(manager, AsyncStateManager)

    @pytest.mark.asyncio
    async def test_creates_database_and_parent_directory_on_first_use(self, manager):
        assert not manager._database_path.parent.exists()
        await manager.load_processed_ids()
        assert manager._database_path.is_file()

    def test_can_be_constructed_outside_a_running_loop(self, tmp_path):
        manager = AsyncSqliteStateManager(tmp_path / "state.db")

        async def mark_and_reload() -> set[str]:
            try:
                await manager.mark_processed("outside")
                return await manager.load_processed_ids()
            finally:
                await manager.aclose()

        assert asyncio.run(mark_and_reload()) == {"outside"}

    @pytest.mark.asyncio
    async def test_connection_is_reused_across_calls(self, manager, mocker):
        connect = mocker.spy(sqlite3, "connect")
        await manager.load_processed_ids()
        await manager.load_processed_ids()
        assert connect.call_count == 1

    @pytest.mark.asyncio
    async def test_connects_in_autocommit_mode_with_timeout_and_full_sync(self, manager, mocker):
        connect = mocker.spy(sqlite3, "connect")
        await manager.load_processed_ids()
        assert connect.call_args == mocker.call(
            manager._database_path, timeout=30.0, check_same_thread=False, isolation_level=None
        )
        assert connect.spy_return.execute("PRAGMA synchronous").fetchone()[0] == 2

    @pytest.mark.asyncio
    async def test_journal_mode_is_write_ahead_logging(self, manager):
        await manager.load_processed_ids()
        with closing(sqlite3.connect(manager._database_path)) as reader:
            mode = reader.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"


class TestAsyncSqliteStateManagerIds:
    @pytest.mark.asyncio
    async def test_empty_before_any_write(self, manager):
        assert await manager.load_processed_ids() == set()

    @pytest.mark.asyncio
    async def test_mark_and_reload(self, manager):
        await manager.mark_processed("abc123")
        await manager.mark_processed("def456")
        assert await manager.load_processed_ids() == {"abc123", "def456"}

    @pytest.mark.asyncio
    async def test_mark_ignores_empty_id(self, manager):
        await manager.mark_processed("")
        assert await manager.load_processed_ids() == set()

    @pytest.mark.asyncio
    async def test_duplicate_id_is_idempotent(self, manager):
        await manager.mark_processed("dup")
        await manager.mark_processed("dup")
        assert await manager.load_processed_ids() == {"dup"}

    @pytest.mark.parametrize(
        "stored",
        [
            "http://arxiv.org/abs/2401.00001",
            "http://arxiv.org/pdf/2401.00002.pdf",
            "2401.00003",
        ],
    )
    @pytest.mark.asyncio
    async def test_ids_stored_verbatim(self, manager, stored):
        await manager.mark_processed(stored)
        assert stored in await manager.load_processed_ids()

    @pytest.mark.asyncio
    async def test_concurrent_marks_lose_no_updates(self, manager):
        await asyncio.gather(*(manager.mark_processed(f"id{index}") for index in range(100)))
        assert len(await manager.load_processed_ids()) == 100

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_marks_collapse(self, manager):
        await asyncio.gather(*(manager.mark_processed(f"id{index % 10}") for index in range(100)))
        assert len(await manager.load_processed_ids()) == 10


class TestAsyncSqliteStateManagerMetadata:
    @pytest.mark.asyncio
    async def test_defaults_when_absent(self, manager):
        metadata = await manager.load_metadata()
        assert metadata.cursor is None
        assert metadata.last_run_at is None

    @pytest.mark.asyncio
    async def test_round_trip_stamps_run_time(self, manager):
        metadata = await manager.load_metadata()
        metadata.cursor = "50"
        await manager.save_metadata(metadata)
        reloaded = await manager.load_metadata()
        assert reloaded.cursor == "50"
        assert reloaded.last_run_at is not None

    @pytest.mark.asyncio
    async def test_second_save_updates_the_single_row(self, manager):
        await manager.save_metadata(PipelineMetadata(cursor="11"))
        await manager.save_metadata(PipelineMetadata(cursor="42"))
        assert (await manager.load_metadata()).cursor == "42"
        with closing(sqlite3.connect(manager._database_path)) as reader:
            rows = reader.execute("SELECT COUNT(*) FROM pipeline_metadata").fetchone()
        assert rows[0] == 1

    @pytest.mark.asyncio
    async def test_metadata_and_ids_are_independent(self, manager):
        await manager.mark_processed("only-id")
        await manager.save_metadata(PipelineMetadata(cursor="3"))
        assert await manager.load_processed_ids() == {"only-id"}
        assert (await manager.load_metadata()).cursor == "3"


class TestAsyncSqliteStateManagerErrors:
    @pytest.mark.asyncio
    async def test_file_that_is_not_a_database_raises_the_sqlite_error_unwrapped(self, tmp_path):
        path = tmp_path / "state.db"
        path.write_bytes(b"definitely not sqlite " * 50)
        manager = AsyncSqliteStateManager(path)
        try:
            with pytest.raises(sqlite3.DatabaseError) as caught:
                await manager.load_processed_ids()
            assert type(caught.value) is sqlite3.DatabaseError
            assert str(caught.value) == "file is not a database"
            assert caught.value.__cause__ is None
        finally:
            await manager.aclose()

    @pytest.mark.parametrize(
        ("operation", "table"),
        [
            (lambda manager: manager.load_processed_ids(), "processed_ids"),
            (lambda manager: manager.mark_processed("id"), "processed_ids"),
            (lambda manager: manager.load_metadata(), "pipeline_metadata"),
            (lambda manager: manager.save_metadata(PipelineMetadata()), "pipeline_metadata"),
        ],
        ids=["load-ids", "mark", "load-metadata", "save-metadata"],
    )
    @pytest.mark.asyncio
    async def test_operation_failure_raises_the_sqlite_error_unwrapped(self, manager, operation, table):
        await manager.load_processed_ids()
        _drop_table(manager._database_path, table)
        with pytest.raises(sqlite3.OperationalError) as caught:
            await operation(manager)
        assert type(caught.value) is sqlite3.OperationalError
        assert str(caught.value) == f"no such table: {table}"
        assert caught.value.__cause__ is None


class TestAsyncSqliteStateManagerDurability:
    @pytest.mark.asyncio
    async def test_flush_leaves_state_readable(self, manager):
        await manager.mark_processed("kept")
        await manager.save_metadata(PipelineMetadata(cursor="9"))
        await manager.flush()
        assert await manager.load_processed_ids() == {"kept"}
        assert (await manager.load_metadata()).cursor == "9"

    @pytest.mark.asyncio
    async def test_aclose_is_safe_before_any_connection(self, manager, mocker):
        connect = mocker.spy(sqlite3, "connect")
        await manager.aclose()
        assert connect.call_count == 0

    @pytest.mark.asyncio
    async def test_aclose_releases_and_reconnects(self, manager, mocker):
        connect = mocker.spy(sqlite3, "connect")
        await manager.mark_processed("kept")
        await manager.aclose()
        with pytest.raises(sqlite3.ProgrammingError):
            connect.spy_return.execute("SELECT 1")
        assert await manager.load_processed_ids() == {"kept"}
        assert connect.call_count == 2

    @pytest.mark.asyncio
    async def test_aclose_is_idempotent(self, manager, mocker):
        connect = mocker.spy(sqlite3, "connect")
        await manager.load_processed_ids()
        await manager.aclose()
        await manager.aclose()
        with pytest.raises(sqlite3.ProgrammingError):
            connect.spy_return.execute("SELECT 1")
        assert connect.call_count == 1

    @pytest.mark.asyncio
    async def test_state_survives_a_new_manager_instance(self, manager, tmp_path):
        await manager.mark_processed("persisted")
        await manager.save_metadata(PipelineMetadata(cursor="17"))
        await manager.aclose()

        reopened = AsyncSqliteStateManager(tmp_path / "nested" / "state.db")
        try:
            assert await reopened.load_processed_ids() == {"persisted"}
            assert (await reopened.load_metadata()).cursor == "17"
        finally:
            await reopened.aclose()

    @pytest.mark.asyncio
    async def test_committed_rows_are_visible_to_an_external_reader(self, manager):
        await manager.mark_processed("committed")
        reader = sqlite3.connect(manager._database_path)
        try:
            rows = reader.execute("SELECT record_id FROM processed_ids").fetchall()
        finally:
            reader.close()
        assert rows == [("committed",)]


class TestAsyncSqliteStateManagerCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_mark_keeps_the_connection_until_its_thread_finishes(self, manager, statement_gate):
        gate = statement_gate(blocked_prefix="INSERT OR IGNORE INTO processed_ids", observed_prefix="SELECT record_id")
        mark = asyncio.create_task(manager.mark_processed("first"))
        await asyncio.to_thread(gate.blocked.wait, 5)
        mark.cancel()
        load = asyncio.create_task(manager.load_processed_ids())
        load_overlapped = await asyncio.to_thread(gate.observed.wait, 0.5)
        gate.release.set()
        await asyncio.to_thread(gate.finished.wait, 5)
        with pytest.raises(asyncio.CancelledError):
            await mark
        assert not load_overlapped
        assert await load == {"first"}
        assert gate.events == ["first-start", "first-end", "second-start"]


class TestAsyncSqliteStateManagerHeadIds:
    @pytest.mark.asyncio
    async def test_head_ids_and_offset_round_trip(self, manager):
        await manager.save_metadata(
            PipelineMetadata(cursor="9", head_ids=["b", "a"], head_offset=4, tail_ids=["y", "z"])
        )
        reloaded = await manager.load_metadata()
        assert reloaded.head_ids == ["b", "a"]
        assert reloaded.head_offset == 4
        assert reloaded.tail_ids == ["y", "z"]

    @pytest.mark.asyncio
    async def test_a_database_created_before_head_ids_existed_gains_the_columns(self, tmp_path):
        path = tmp_path / "old.db"
        with closing(sqlite3.connect(path, isolation_level=None)) as connection:
            connection.execute("CREATE TABLE processed_ids (record_id TEXT PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE pipeline_metadata (id INTEGER PRIMARY KEY CHECK (id = 1),"
                " last_run_at TEXT, last_start_index INTEGER NOT NULL DEFAULT 0)"
            )
            connection.execute("INSERT INTO pipeline_metadata VALUES (1, 'then', 17)")
        upgraded = AsyncSqliteStateManager(path)
        try:
            reloaded = await upgraded.load_metadata()
            assert (reloaded.last_run_at, reloaded.cursor) == ("then", "17")
            assert reloaded.head_ids == []
            assert reloaded.head_offset == 0
            assert reloaded.tail_ids == []
            reloaded.head_ids = ["x"]
            await upgraded.save_metadata(reloaded)
            assert (await upgraded.load_metadata()).head_ids == ["x"]
        finally:
            await upgraded.aclose()

    @pytest.mark.asyncio
    async def test_reopening_an_upgraded_database_does_not_add_columns_again(self, manager):
        await manager.save_metadata(PipelineMetadata(head_ids=["kept"]))
        await manager.aclose()
        assert (await manager.load_metadata()).head_ids == ["kept"]
