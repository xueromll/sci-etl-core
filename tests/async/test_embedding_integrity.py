from __future__ import annotations

import asyncio
import math
import sqlite3
import threading

import pytest

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.chunking import SlidingWindowChunker
from sci_etl_core.embeddings.ingest_async import AsyncChunkIngestor
from sci_etl_core.embeddings.store_base import EmbeddingChunk
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.exceptions import EmbeddingError, EmbeddingStoreError
from sci_etl_core.models import RawRecord

KINDS = ["memory", "sqlite"]


def _store(kind: str, tmp_path):
    return InMemoryEmbeddingStore() if kind == "memory" else AsyncSqliteEmbeddingStore(tmp_path / "memory.db")


def _chunk(record_id: str, index: int, vector, text: str | None = None) -> EmbeddingChunk:
    return EmbeddingChunk(record_id, index, text if text is not None else f"{record_id}-{index}", vector)


class _UnitEmbedder(AsyncEmbedder):
    def __init__(self, drop: int = 0) -> None:
        self._drop = drop

    async def embed(self, texts):
        vectors = [[1.0, float(position)] for position, _ in enumerate(texts)]
        return vectors[: len(vectors) - self._drop]


class TestStoreRecordLifecycle:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.asyncio
    async def test_delete_record_removes_only_that_record(self, kind, tmp_path):
        store = _store(kind, tmp_path)
        try:
            await store.add([_chunk("a", 0, [1.0, 0.0]), _chunk("a", 1, [1.0, 0.0]), _chunk("b", 0, [1.0, 0.0])])
            await store.delete_record("a")
            assert [hit.record_id for hit in await store.query([1.0, 0.0], top_k=10)] == ["b"]
        finally:
            await store.aclose()

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.asyncio
    async def test_replace_record_drops_stale_chunks(self, kind, tmp_path):
        store = _store(kind, tmp_path)
        try:
            await store.add([_chunk("a", index, [1.0, 0.0], f"old{index}") for index in range(5)])
            await store.replace_record("a", [_chunk("a", index, [1.0, 0.0], f"new{index}") for index in range(2)])
            hits = await store.query([1.0, 0.0], top_k=10)
            assert sorted(hit.text for hit in hits) == ["new0", "new1"]
        finally:
            await store.aclose()

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.asyncio
    async def test_non_finite_stored_vectors_never_match(self, kind, tmp_path):
        store = _store(kind, tmp_path)
        try:
            await store.add(
                [
                    _chunk("best", 0, [1.0, 0.0, 0.0]),
                    _chunk("nan", 0, [math.nan, 1.0, 0.0]),
                    _chunk("mid", 0, [1.0, 1.0, 0.0]),
                    _chunk("inf", 0, [math.inf, 0.0, 0.0]),
                ]
            )
            hits = await store.query([1.0, 0.0, 0.0], top_k=10, min_score=0.0)
            assert [hit.record_id for hit in hits] == ["best", "mid"]
        finally:
            await store.aclose()


class TestSqliteStoreFailures:
    @pytest.mark.asyncio
    async def test_file_that_is_not_a_database_raises_a_typed_error(self, tmp_path):
        path = tmp_path / "not_a_db.db"
        path.write_bytes(b"definitely not sqlite " * 50)
        store = AsyncSqliteEmbeddingStore(path)
        for _ in range(2):
            with pytest.raises(EmbeddingStoreError, match="Failed to open"):
                await store.count()
        await store.aclose()

    @pytest.mark.asyncio
    async def test_failed_replace_rolls_back_and_keeps_the_old_chunks(self, tmp_path):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            await store.add([_chunk("a", 0, [1.0, 0.0], "kept")])
            broken = EmbeddingChunk("a", 1, None, [1.0, 0.0])
            with pytest.raises(EmbeddingStoreError, match="Failed to replace"):
                await store.replace_record("a", [_chunk("a", 0, [1.0, 0.0], "new"), broken])
            assert [hit.text for hit in await store.query([1.0, 0.0])] == ["kept"]
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_read_failure_is_typed(self, tmp_path, mocker):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        mocker.patch.object(AsyncSqliteEmbeddingStore, "_select", side_effect=sqlite3.OperationalError("disk I/O error"))
        try:
            with pytest.raises(EmbeddingStoreError, match="Failed to read"):
                await store.query([1.0, 0.0])
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_concurrent_writes_are_all_stored(self, tmp_path):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            await asyncio.gather(
                *(store.add([_chunk(f"r{n}", index, [float(n), 1.0]) for index in range(50)]) for n in range(20))
            )
            assert await store.count() == 1000
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_cancelled_caller_holds_the_lock_until_its_thread_finishes(self, tmp_path):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        started, release = threading.Event(), threading.Event()
        real_execute = store._execute

        def blocking_execute(operation):
            started.set()
            release.wait(5)
            return real_execute(operation)

        store._execute = blocking_execute
        task = asyncio.create_task(store.add([_chunk("a", 0, [1.0, 0.0])]))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        assert store._lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not store._lock.locked()
        del store._execute
        try:
            assert await store.count() == 1
        finally:
            await store.aclose()


class TestIngestorReplacesRecords:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.asyncio
    async def test_reingesting_shorter_text_removes_stale_chunks(self, kind, tmp_path):
        store = _store(kind, tmp_path)
        ingestor = AsyncChunkIngestor(SlidingWindowChunker(chunk_words=2, overlap_words=0), _UnitEmbedder(), store)
        record = RawRecord("a", "t", "abstract")
        try:
            assert await ingestor.ingest(record, "one two three four five six") == 3
            assert await ingestor.ingest(record, "one two") == 1
            assert await store.count() == 1
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_empty_text_clears_only_that_record(self):
        store = InMemoryEmbeddingStore()
        ingestor = AsyncChunkIngestor(SlidingWindowChunker(chunk_words=2, overlap_words=0), _UnitEmbedder(), store)
        await ingestor.ingest(RawRecord("a", "t", "abs"), "one two")
        await ingestor.ingest(RawRecord("b", "t", "abs"), "three four")
        assert await ingestor.ingest(RawRecord("a", "t", "abs"), "   ") == 0
        assert [hit.record_id for hit in await store.query([1.0, 0.0])] == ["b"]

    @pytest.mark.asyncio
    async def test_vector_count_mismatch_raises_and_stores_nothing(self):
        store = InMemoryEmbeddingStore()
        ingestor = AsyncChunkIngestor(SlidingWindowChunker(chunk_words=2, overlap_words=0), _UnitEmbedder(drop=1), store)
        with pytest.raises(EmbeddingError, match="1 vectors for 2 passages"):
            await ingestor.ingest(RawRecord("a", "t", "abs"), "one two three four")
        assert await store.count() == 0
