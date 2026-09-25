from __future__ import annotations

import asyncio
import math
import sqlite3
from contextlib import closing

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


def _not_a_database(tmp_path):
    path = tmp_path / "not_a_db.db"
    path.write_bytes(b"definitely not sqlite " * 50)
    return path


def _drop_table(path, table: str) -> None:
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute(f"DROP TABLE {table}")


def _verbs(statements: list[str]) -> list[str]:
    return [statement.split()[0].upper() for statement in statements]


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

    @pytest.mark.parametrize(
        ("make_path", "message", "cause"),
        [
            (
                lambda tmp_path: tmp_path,
                "Failed to open the SQLite embedding store: unable to open database file",
                sqlite3.OperationalError,
            ),
            (
                _not_a_database,
                "Failed to open the SQLite embedding store: file is not a database",
                sqlite3.DatabaseError,
            ),
        ],
        ids=["directory", "not-a-database"],
    )
    @pytest.mark.asyncio
    async def test_open_failure_message_is_exact(self, tmp_path, make_path, message, cause):
        store = AsyncSqliteEmbeddingStore(make_path(tmp_path))
        try:
            with pytest.raises(EmbeddingStoreError) as caught:
                await store.count()
            assert type(caught.value) is EmbeddingStoreError
            assert str(caught.value) == message
            assert type(caught.value.__cause__) is cause
        finally:
            await store.aclose()

    @pytest.mark.parametrize(
        ("operation", "message"),
        [
            (
                lambda store: store.add([_chunk("a", 0, [1.0, 0.0])]),
                "Failed to write chunk embeddings: no such table: chunks",
            ),
            (
                lambda store: store.delete_record("a"),
                "Failed to delete chunk embeddings: no such table: chunks",
            ),
            (
                lambda store: store.replace_record("a", [_chunk("a", 0, [1.0, 0.0])]),
                "Failed to replace chunk embeddings: no such table: chunks",
            ),
            (
                lambda store: store.query([1.0, 0.0]),
                "Failed to read chunk embeddings: no such table: chunks",
            ),
            (
                lambda store: store.count(),
                "Failed to count chunk embeddings: no such table: chunks",
            ),
        ],
        ids=["write", "delete", "replace", "read", "count"],
    )
    @pytest.mark.asyncio
    async def test_operation_failure_message_is_exact(self, tmp_path, operation, message):
        path = tmp_path / "memory.db"
        store = AsyncSqliteEmbeddingStore(path)
        try:
            await store.count()
            _drop_table(path, "chunks")
            with pytest.raises(EmbeddingStoreError) as caught:
                await operation(store)
            assert type(caught.value) is EmbeddingStoreError
            assert str(caught.value) == message
            assert type(caught.value.__cause__) is sqlite3.OperationalError
        finally:
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
    async def test_replace_record_is_a_single_transaction(self, tmp_path, mocker):
        connect = mocker.spy(sqlite3, "connect")
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            await store.add([_chunk("a", index, [1.0, 0.0], f"old{index}") for index in range(3)])
            statements: list[str] = []
            connect.spy_return.set_trace_callback(statements.append)
            await store.replace_record("a", [_chunk("a", index, [1.0, 0.0], f"new{index}") for index in range(2)])
            assert _verbs(statements) == ["BEGIN", "DELETE", "INSERT", "INSERT", "COMMIT"]
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_failed_replace_record_rolls_back_its_single_transaction(self, tmp_path, mocker):
        connect = mocker.spy(sqlite3, "connect")
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            await store.add([_chunk("a", 0, [1.0, 0.0], "kept")])
            statements: list[str] = []
            connect.spy_return.set_trace_callback(statements.append)
            broken = EmbeddingChunk("a", 1, None, [1.0, 0.0])
            with pytest.raises(EmbeddingStoreError):
                await store.replace_record("a", [_chunk("a", 0, [1.0, 0.0], "new"), broken])
            assert _verbs(statements) == ["BEGIN", "DELETE", "INSERT", "INSERT", "ROLLBACK"]
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_read_failure_is_typed(self, tmp_path, mocker):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        mocker.patch.object(
            AsyncSqliteEmbeddingStore, "_select", side_effect=sqlite3.OperationalError("disk I/O error")
        )
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
    async def test_cancelled_writer_keeps_the_connection_until_its_thread_finishes(self, tmp_path, statement_gate):
        gate = statement_gate(blocked_prefix="INSERT OR REPLACE INTO chunks", observed_prefix="SELECT COUNT")
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            write = asyncio.create_task(store.add([_chunk("a", 0, [1.0, 0.0])]))
            await asyncio.to_thread(gate.blocked.wait, 5)
            write.cancel()
            count = asyncio.create_task(store.count())
            count_overlapped = await asyncio.to_thread(gate.observed.wait, 0.5)
            gate.release.set()
            await asyncio.to_thread(gate.finished.wait, 5)
            with pytest.raises(asyncio.CancelledError):
                await write
            assert not count_overlapped
            assert await count == 1
            assert gate.events == ["first-start", "first-end", "second-start"]
        finally:
            await store.aclose()


class TestIngestorReplacesRecords:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.asyncio
    async def test_reingesting_shorter_text_removes_stale_chunks(self, kind, tmp_path):
        store = _store(kind, tmp_path)
        ingestor = AsyncChunkIngestor(SlidingWindowChunker(chunk_words=2, overlap_words=0), _UnitEmbedder(), store)
        record = RawRecord(record_id="a", title="t", abstract="abstract")
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
        await ingestor.ingest(RawRecord(record_id="a", title="t", abstract="abs"), "one two")
        await ingestor.ingest(RawRecord(record_id="b", title="t", abstract="abs"), "three four")
        assert await ingestor.ingest(RawRecord(record_id="a", title="t", abstract="abs"), "   ") == 0
        assert [hit.record_id for hit in await store.query([1.0, 0.0])] == ["b"]

    @pytest.mark.asyncio
    async def test_vector_count_mismatch_raises_and_stores_nothing(self):
        store = InMemoryEmbeddingStore()
        chunker = SlidingWindowChunker(chunk_words=2, overlap_words=0)
        ingestor = AsyncChunkIngestor(chunker, _UnitEmbedder(drop=1), store)
        with pytest.raises(EmbeddingError, match="1 vectors for 2 passages"):
            await ingestor.ingest(RawRecord(record_id="a", title="t", abstract="abs"), "one two three four")
        assert await store.count() == 0
