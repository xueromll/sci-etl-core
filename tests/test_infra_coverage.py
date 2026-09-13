from __future__ import annotations

import asyncio

import pytest

from sci_etl_core import _file_lock, _sync_bridge
from sci_etl_core._atomic_io import atomic_write_text
from sci_etl_core.embeddings.store_base import EmbeddingChunk
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.models import PipelineMetadata
from sci_etl_core.rate_limiter import SemaphoreRateLimiter
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.async_file_state import AsyncFileStateManager


class TestAtomicWrite:
    def test_temp_file_is_removed_when_replace_fails(self, tmp_path, mocker):
        target = tmp_path / "out.txt"
        mocker.patch(
            "sci_etl_core._atomic_io.os.replace", side_effect=OSError("replace failed")
        )
        with pytest.raises(OSError):
            atomic_write_text(target, "payload")
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []


class TestExclusiveLock:
    def test_uses_fcntl_when_available(self, mocker):
        fake = mocker.MagicMock(LOCK_EX=2, LOCK_UN=8)
        mocker.patch.object(_file_lock, "fcntl", fake)
        mocker.patch.object(_file_lock, "msvcrt", None)
        handle = mocker.MagicMock()
        handle.fileno.return_value = 7
        with _file_lock.exclusive_lock(handle):
            pass
        fake.flock.assert_any_call(7, 2)
        fake.flock.assert_any_call(7, 8)

    def test_uses_msvcrt_when_fcntl_missing(self, mocker):
        fake = mocker.MagicMock(LK_LOCK=1, LK_UNLCK=0)
        mocker.patch.object(_file_lock, "fcntl", None)
        mocker.patch.object(_file_lock, "msvcrt", fake)
        handle = mocker.MagicMock()
        handle.fileno.return_value = 7
        with _file_lock.exclusive_lock(handle):
            pass
        assert fake.locking.call_count == 2

    def test_is_a_noop_without_any_backend(self, mocker):
        mocker.patch.object(_file_lock, "fcntl", None)
        mocker.patch.object(_file_lock, "msvcrt", None)
        handle = mocker.MagicMock()
        with _file_lock.exclusive_lock(handle):
            pass
        handle.fileno.assert_not_called()


class TestSemaphoreRateLimiterExtras:
    @pytest.mark.asyncio
    async def test_held_reports_checked_out_slots(self):
        limiter = SemaphoreRateLimiter(2)
        async with limiter:
            assert limiter.held == 1
        assert limiter.held == 0

    @pytest.mark.asyncio
    async def test_slot_is_released_when_bookkeeping_fails(self):
        limiter = SemaphoreRateLimiter(1)
        limiter._held = object()  # make ``self._held += 1`` raise
        with pytest.raises(TypeError):
            await limiter.__aenter__()
        await asyncio.wait_for(limiter._semaphore.acquire(), timeout=0.1)


class TestSyncBridgeExtras:
    def test_set_default_timeout_updates_module_default(self):
        original = _sync_bridge._default_timeout
        try:
            _sync_bridge.set_default_timeout(0.5)
            assert _sync_bridge._default_timeout == 0.5
            _sync_bridge.set_default_timeout(None)
            assert _sync_bridge._default_timeout is None
        finally:
            _sync_bridge.set_default_timeout(original)

    def test_run_sync_times_out_and_cancels(self):
        async def _never() -> None:
            await asyncio.sleep(3600)

        with pytest.raises(TimeoutError, match="did not complete"):
            _sync_bridge.run_sync(_never(), timeout=0.05)


class _NoopStateManager(AsyncStateManager):
    async def load_processed_ids(self) -> set[str]:
        return set()

    async def mark_processed(self, record_id: str) -> None:
        return None

    async def load_metadata(self) -> PipelineMetadata:
        return PipelineMetadata()

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        return None


class TestStateManagerDefaultFlush:
    @pytest.mark.asyncio
    async def test_default_flush_is_a_noop(self):
        assert await _NoopStateManager().flush() is None


class TestFileStateWhitespaceIds:
    @pytest.mark.asyncio
    async def test_whitespace_only_id_is_ignored(self, tmp_path):
        state = AsyncFileStateManager(tmp_path / "ids.txt", tmp_path / "meta.json")
        await state.mark_processed("   ")
        assert not (tmp_path / "ids.txt").exists()


class TestSqliteEmbeddingStoreCancellation:
    @pytest.mark.asyncio
    async def test_cancellation_during_a_write_is_not_wrapped(self, tmp_path, mocker):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        connection = await store._connect()
        mocker.patch.object(connection, "executemany", side_effect=asyncio.CancelledError())
        try:
            with pytest.raises(asyncio.CancelledError):
                await store.add([EmbeddingChunk("r", 0, "text", [1.0, 0.0])])
        finally:
            await store.aclose()
