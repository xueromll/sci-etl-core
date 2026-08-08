from __future__ import annotations

import json

import pytest

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_file_state import AsyncFileStateManager


@pytest.fixture
def manager(tmp_path) -> AsyncFileStateManager:
    return AsyncFileStateManager(tmp_path / "ids.txt", tmp_path / "meta.json")


class TestAsyncFileStateManager:
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

    @pytest.mark.parametrize(
        "stored, expected",
        [
            ("http://arxiv.org/abs/2401.00001", "2401.00001"),
            ("http://arxiv.org/pdf/2401.00002.pdf", "2401.00002"),
            ("2401.00003", "2401.00003"),
        ],
    )
    @pytest.mark.asyncio
    async def test_ids_cleaned_on_load(self, manager, stored, expected):
        manager._processed_ids_file.write_text(stored + "\n", encoding="utf-8")
        assert expected in await manager.load_processed_ids()

    @pytest.mark.asyncio
    async def test_metadata_defaults_when_absent(self, manager):
        meta = await manager.load_metadata()
        assert meta.last_start_index == 0
        assert meta.last_run_at is None

    @pytest.mark.asyncio
    async def test_metadata_round_trip_stamps_run_time(self, manager):
        meta = await manager.load_metadata()
        meta.last_start_index = 50
        await manager.save_metadata(meta)
        reloaded = await manager.load_metadata()
        assert reloaded.last_start_index == 50
        assert reloaded.last_run_at is not None

    @pytest.mark.asyncio
    async def test_corrupted_metadata_falls_back(self, manager):
        manager._metadata_file.write_text("{ not valid json", encoding="utf-8")
        assert (await manager.load_metadata()).last_start_index == 0

    @pytest.mark.asyncio
    async def test_saved_metadata_is_readable_json(self, manager):
        await manager.save_metadata(PipelineMetadata(last_start_index=7))
        payload = json.loads(manager._metadata_file.read_text(encoding="utf-8"))
        assert payload["last_start_index"] == 7
        assert "last_run_date" in payload
