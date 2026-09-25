from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import pytest_asyncio

from sci_etl_core import (
    AsyncFileStateManager,
    AsyncSqliteEmbeddingStore,
    AsyncSqliteLLMResponseCache,
    AsyncSqliteStateManager,
    EmbeddingStoreError,
    LLMCacheError,
    PipelineMetadata,
    StateStoreError,
)
from sci_etl_core.state._failures import ERROR_TEXT_LIMIT, TRUNCATION_MARKER, bounded_error_text
from sci_etl_core.state.async_base import AsyncStateManager


class _Minimal(AsyncStateManager):
    async def load_processed_ids(self) -> set[str]:
        return set()

    async def mark_processed(self, record_id: str) -> None:
        return None

    async def load_metadata(self) -> PipelineMetadata:
        return PipelineMetadata()

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        return None


def _file_manager(tmp_path: Path) -> AsyncFileStateManager:
    return AsyncFileStateManager(tmp_path / "ids.txt", tmp_path / "meta.json")


def _sqlite_manager(tmp_path: Path) -> AsyncSqliteStateManager:
    return AsyncSqliteStateManager(tmp_path / "state.sqlite")


@pytest_asyncio.fixture(params=[_file_manager, _sqlite_manager], ids=["file", "sqlite"])
async def manager(request, tmp_path):
    state = request.param(tmp_path)
    yield state
    aclose = getattr(state, "aclose", None)
    if aclose is not None:
        await aclose()


def _future_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version = 99")


class TestFailureTrackingContract:
    @pytest.mark.asyncio
    async def test_the_defaults_track_nothing(self):
        state = _Minimal()
        assert await state.record_failure("a", "boom") == 0
        assert await state.failure_counts() == {}

    def test_long_error_text_is_cut_with_a_marker(self):
        assert bounded_error_text("short") == "short"
        long = bounded_error_text("x" * (ERROR_TEXT_LIMIT + 10))
        assert len(long) == ERROR_TEXT_LIMIT
        assert long.endswith(TRUNCATION_MARKER)


class TestBundledStateManagersTrackFailures:
    @pytest.mark.asyncio
    async def test_attempts_are_counted_and_cleared_when_the_record_is_processed(self, manager):
        assert await manager.record_failure("a", "LLMError: timeout") == 1
        assert await manager.record_failure("a", "LLMError: timeout") == 2
        assert await manager.record_failure("b", "UpstreamError: down") == 1
        assert await manager.failure_counts() == {"a": 2, "b": 1}

        await manager.mark_processed("a")

        assert await manager.failure_counts() == {"b": 1}
        assert await manager.load_processed_ids() == {"a"}

    @pytest.mark.asyncio
    async def test_a_blank_record_id_counts_nothing(self, manager):
        assert await manager.record_failure("", "boom") == 0
        assert await manager.failure_counts() == {}

    @pytest.mark.asyncio
    async def test_saving_metadata_keeps_the_recorded_failures(self, manager):
        await manager.record_failure("a", "boom")
        await manager.save_metadata(PipelineMetadata(cursor="7", truncated=True))

        assert await manager.failure_counts() == {"a": 1}
        metadata = await manager.load_metadata()
        assert (metadata.cursor, metadata.truncated) == ("7", True)


class TestFileStateFailures:
    @pytest.mark.asyncio
    async def test_the_last_error_is_stored_truncated(self, tmp_path):
        state = _file_manager(tmp_path)
        await state.record_failure("a", "first")
        await state.record_failure("a", "e" * 5000)

        stored = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["failures"]["a"]
        assert stored["attempts"] == 2
        assert len(stored["last_error"]) == ERROR_TEXT_LIMIT

    @pytest.mark.asyncio
    async def test_failures_survive_a_new_instance_and_marking_clears_them(self, tmp_path):
        await _file_manager(tmp_path).record_failure("a", "boom")
        reopened = _file_manager(tmp_path)

        await reopened.mark_processed("a")

        assert await _file_manager(tmp_path).failure_counts() == {}

    @pytest.mark.asyncio
    async def test_marking_a_record_without_failures_leaves_the_metadata_file_alone(self, tmp_path):
        state = _file_manager(tmp_path)
        await state.mark_processed("a")
        assert not (tmp_path / "meta.json").exists()

    @pytest.mark.asyncio
    async def test_unreadable_failure_entries_are_ignored(self, tmp_path):
        failures = {"a": {"attempts": 2}, "b": {"attempts": "x"}, "c": 3, "d": {"attempts": 0}}
        (tmp_path / "meta.json").write_text(
            json.dumps({"schema_version": 2, "failures": failures}), encoding="utf-8"
        )
        assert await _file_manager(tmp_path).failure_counts() == {"a": 2}

    @pytest.mark.asyncio
    async def test_a_failures_value_that_is_not_a_mapping_reads_as_none(self, tmp_path):
        (tmp_path / "meta.json").write_text(json.dumps({"schema_version": 2, "failures": []}), encoding="utf-8")
        assert await _file_manager(tmp_path).failure_counts() == {}

    @pytest.mark.parametrize("version", ["2", True, 0])
    @pytest.mark.asyncio
    async def test_an_unreadable_schema_version_reads_as_a_0_4_file(self, tmp_path, version):
        (tmp_path / "meta.json").write_text(
            json.dumps({"schema_version": version, "last_start_index": 5, "cursor": "ignored"}), encoding="utf-8"
        )
        assert (await _file_manager(tmp_path).load_metadata()).cursor == "5"

    @pytest.mark.asyncio
    async def test_a_cursor_that_is_not_text_reads_as_the_first_page(self, tmp_path):
        (tmp_path / "meta.json").write_text(json.dumps({"schema_version": 2, "cursor": 5}), encoding="utf-8")
        assert (await _file_manager(tmp_path).load_metadata()).cursor is None

    @pytest.mark.asyncio
    async def test_a_file_written_by_a_newer_release_is_refused_and_kept(self, tmp_path):
        payload = json.dumps({"schema_version": 3, "cursor": "x"})
        (tmp_path / "meta.json").write_text(payload, encoding="utf-8")
        state = _file_manager(tmp_path)

        with pytest.raises(StateStoreError, match="state metadata file has schema version 3"):
            await state.load_metadata()
        with pytest.raises(StateStoreError):
            await state.save_metadata(PipelineMetadata())
        assert (tmp_path / "meta.json").read_text(encoding="utf-8") == payload


class TestSchemaVersions:
    @pytest.mark.asyncio
    async def test_a_state_database_from_a_newer_release_is_refused(self, tmp_path):
        _future_database(tmp_path / "state.sqlite")
        state = _sqlite_manager(tmp_path)
        with pytest.raises(StateStoreError, match="state database has schema version 99, newer than version 2"):
            await state.load_processed_ids()
        await state.aclose()

    @pytest.mark.asyncio
    async def test_an_llm_cache_from_a_newer_release_is_refused(self, tmp_path):
        _future_database(tmp_path / "cache.sqlite")
        cache = AsyncSqliteLLMResponseCache(tmp_path / "cache.sqlite")
        with pytest.raises(LLMCacheError, match="LLM response cache has schema version 99"):
            await cache.get("key")
        await cache.aclose()

    @pytest.mark.asyncio
    async def test_an_embedding_store_from_a_newer_release_is_refused(self, tmp_path):
        _future_database(tmp_path / "embeddings.sqlite")
        store = AsyncSqliteEmbeddingStore(tmp_path / "embeddings.sqlite")
        with pytest.raises(EmbeddingStoreError, match="embedding store has schema version 99"):
            await store.count()
        await store.aclose()

    @pytest.mark.asyncio
    async def test_new_files_record_their_schema_version(self, tmp_path):
        state = _sqlite_manager(tmp_path)
        await state.load_processed_ids()
        await state.aclose()
        cache = AsyncSqliteLLMResponseCache(tmp_path / "cache.sqlite")
        await cache.get("key")
        await cache.aclose()
        with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        with closing(sqlite3.connect(tmp_path / "cache.sqlite")) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
