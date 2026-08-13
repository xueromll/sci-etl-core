from __future__ import annotations

import asyncio
import sqlite3

import pytest

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.sqlite_async import AsyncSqliteStateManager


@pytest.fixture
def manager(tmp_path) -> AsyncSqliteStateManager:
    instance = AsyncSqliteStateManager(tmp_path / "nested" / "state.db")
    yield instance
    if instance._connection is not None:
        instance._connection.close()


class TestAsyncSqliteStateManagerContract:
    def test_implements_the_async_state_manager_abc(self, manager):
        assert isinstance(manager, AsyncStateManager)

    @pytest.mark.asyncio
    async def test_creates_database_and_parent_directory_on_first_use(self, manager):
        assert not manager._database_path.parent.exists()
        await manager.load_processed_ids()
        assert manager._database_path.is_file()

    @pytest.mark.asyncio
    async def test_lock_is_created_once(self, manager):
        await manager.load_processed_ids()
        assert manager._get_lock() is manager._get_lock()

    @pytest.mark.asyncio
    async def test_connection_is_reused_across_calls(self, manager):
        await manager.load_processed_ids()
        first = manager._connection
        await manager.load_processed_ids()
        assert manager._connection is first

    @pytest.mark.asyncio
    async def test_journal_mode_is_write_ahead_logging(self, manager):
        await manager.load_processed_ids()
        mode = manager._connection.execute("PRAGMA journal_mode").fetchone()[0]
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
        assert metadata.last_start_index == 0
        assert metadata.last_run_at is None

    @pytest.mark.asyncio
    async def test_round_trip_stamps_run_time(self, manager):
        metadata = await manager.load_metadata()
        metadata.last_start_index = 50
        await manager.save_metadata(metadata)
        reloaded = await manager.load_metadata()
        assert reloaded.last_start_index == 50
        assert reloaded.last_run_at is not None

    @pytest.mark.asyncio
    async def test_second_save_updates_the_single_row(self, manager):
        await manager.save_metadata(PipelineMetadata(last_start_index=11))
        await manager.save_metadata(PipelineMetadata(last_start_index=42))
        assert (await manager.load_metadata()).last_start_index == 42
        rows = manager._connection.execute("SELECT COUNT(*) FROM pipeline_metadata").fetchone()
        assert rows[0] == 1

    @pytest.mark.asyncio
    async def test_metadata_and_ids_are_independent(self, manager):
        await manager.mark_processed("only-id")
        await manager.save_metadata(PipelineMetadata(last_start_index=3))
        assert await manager.load_processed_ids() == {"only-id"}
        assert (await manager.load_metadata()).last_start_index == 3


class TestAsyncSqliteStateManagerDurability:
    @pytest.mark.asyncio
    async def test_flush_leaves_state_readable(self, manager):
        await manager.mark_processed("kept")
        await manager.save_metadata(PipelineMetadata(last_start_index=9))
        await manager.flush()
        assert await manager.load_processed_ids() == {"kept"}
        assert (await manager.load_metadata()).last_start_index == 9

    @pytest.mark.asyncio
    async def test_aclose_is_safe_before_any_connection(self, manager):
        await manager.aclose()
        assert manager._connection is None

    @pytest.mark.asyncio
    async def test_aclose_releases_and_reconnects(self, manager):
        await manager.mark_processed("kept")
        await manager.aclose()
        assert manager._connection is None
        assert await manager.load_processed_ids() == {"kept"}
        assert manager._connection is not None

    @pytest.mark.asyncio
    async def test_aclose_is_idempotent(self, manager):
        await manager.load_processed_ids()
        await manager.aclose()
        await manager.aclose()
        assert manager._connection is None

    @pytest.mark.asyncio
    async def test_state_survives_a_new_manager_instance(self, manager, tmp_path):
        await manager.mark_processed("persisted")
        await manager.save_metadata(PipelineMetadata(last_start_index=17))
        await manager.aclose()

        reopened = AsyncSqliteStateManager(tmp_path / "nested" / "state.db")
        try:
            assert await reopened.load_processed_ids() == {"persisted"}
            assert (await reopened.load_metadata()).last_start_index == 17
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
