from __future__ import annotations

import json
from datetime import datetime, timedelta

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
        "stored",
        [
            "http://arxiv.org/abs/2401.00001",
            "http://arxiv.org/pdf/2401.00002.pdf",
            "2401.00003",
        ],
    )
    @pytest.mark.asyncio
    async def test_ids_loaded_verbatim(self, manager, stored):
        manager._processed_ids_file.write_text(stored + "\n", encoding="utf-8")
        assert stored in await manager.load_processed_ids()

    @pytest.mark.asyncio
    async def test_unreadable_ids_file_raises_instead_of_reading_as_empty(self, manager, mocker):
        manager._processed_ids_file.write_text("2401.1\n", encoding="utf-8")
        mocker.patch(
            "sci_etl_core.state.async_file_state.Path.open", side_effect=OSError("io")
        )
        with pytest.raises(OSError, match="io"):
            await manager.load_processed_ids()

    @pytest.mark.asyncio
    async def test_unreadable_metadata_file_raises(self, manager, mocker):
        manager._metadata_file.write_text('{"last_start_index": 5}', encoding="utf-8")
        mocker.patch(
            "sci_etl_core.state.async_file_state.Path.open", side_effect=OSError("io")
        )
        with pytest.raises(OSError, match="io"):
            await manager.load_metadata()

    @pytest.mark.parametrize(
        "boundary", ["\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]
    )
    @pytest.mark.asyncio
    async def test_ids_containing_any_line_boundary_are_rejected(self, manager, boundary):
        with pytest.raises(ValueError, match="line boundary"):
            await manager.mark_processed(f"2401.1{boundary}2401.2")
        assert await manager.load_processed_ids() == set()

    @pytest.mark.parametrize("record_id", [" 2401.1", "2401.1 ", "\t2401.1", "2401.1\n"])
    @pytest.mark.asyncio
    async def test_ids_with_surrounding_whitespace_are_rejected(self, manager, record_id):
        with pytest.raises(ValueError, match="leading or trailing whitespace"):
            await manager.mark_processed(record_id)
        assert await manager.load_processed_ids() == set()

    @pytest.mark.parametrize(
        "payload",
        [
            '{"last_start_index": "7"}',
            '{"last_start_index": -3}',
            '{"last_start_index": true}',
            '{"last_start_index": null}',
            '{"last_run_date": 5}',
            "[1, 2]",
        ],
    )
    @pytest.mark.asyncio
    async def test_invalid_metadata_values_fall_back_to_defaults(self, manager, payload):
        manager._metadata_file.write_text(payload, encoding="utf-8")
        meta = await manager.load_metadata()
        assert meta.last_start_index == 0
        assert meta.last_run_at is None

    @pytest.mark.asyncio
    async def test_metadata_that_is_not_utf8_falls_back(self, manager):
        manager._metadata_file.write_bytes(b'{"last_start_index": \xff}')
        assert (await manager.load_metadata()).last_start_index == 0

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
    async def test_run_time_is_stamped_with_a_utc_offset(self, manager):
        await manager.save_metadata(PipelineMetadata(last_start_index=1))
        reloaded = await manager.load_metadata()
        assert datetime.fromisoformat(reloaded.last_run_at).utcoffset() == timedelta(0)

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


class TestAsyncFileStateManagerHeadIds:
    @pytest.mark.asyncio
    async def test_head_ids_and_offset_round_trip(self, manager):
        await manager.save_metadata(
            PipelineMetadata(last_start_index=9, head_ids=["b", "a"], head_offset=4, tail_ids=["y", "z"])
        )
        reloaded = await manager.load_metadata()
        assert reloaded.head_ids == ["b", "a"]
        assert reloaded.head_offset == 4
        assert reloaded.tail_ids == ["y", "z"]

    @pytest.mark.asyncio
    async def test_a_file_written_before_head_ids_existed_loads_with_defaults(self, manager):
        manager._metadata_file.write_text('{"last_start_index": 12, "last_run_date": "x"}', encoding="utf-8")
        reloaded = await manager.load_metadata()
        assert reloaded.last_start_index == 12
        assert reloaded.head_ids == []
        assert reloaded.head_offset == 0

    @pytest.mark.parametrize(
        "payload",
        [
            '{"head_ids": "abc", "head_offset": "2", "tail_ids": "abc"}',
            '{"head_ids": [1, 2], "head_offset": -1, "tail_ids": [3]}',
            '{"head_ids": null, "head_offset": true, "tail_ids": null}',
        ],
    )
    @pytest.mark.asyncio
    async def test_invalid_head_values_fall_back_to_defaults(self, manager, payload):
        manager._metadata_file.write_text(payload, encoding="utf-8")
        reloaded = await manager.load_metadata()
        assert reloaded.head_ids == []
        assert reloaded.head_offset == 0
        assert reloaded.tail_ids == []
