from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from sci_etl_core._migrations import Migration, migrate, newer_schema_message
from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.embeddings._similarity import unit_vector
from sci_etl_core.embeddings.store_base import (
    AsyncEmbeddingStore,
    EmbeddingChunk,
    SearchHit,
    StoredRecord,
)
from sci_etl_core.exceptions import EmbeddingStoreError

_MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS chunks (
                record_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (record_id, chunk_index)
            )
            """,
        ),
    ),
)
_INSERT = (
    "INSERT OR REPLACE INTO chunks (record_id, chunk_index, text, dim, vector, metadata)"
    " VALUES (?, ?, ?, ?, ?, ?)"
)
_DELETE = "DELETE FROM chunks WHERE record_id = ?"
_SELECT_VECTORS = "SELECT rowid, record_id, vector FROM chunks WHERE dim = ? ORDER BY rowid"
_SELECT_PASSAGES = "SELECT rowid, record_id, chunk_index, text, metadata FROM chunks WHERE rowid IN ({placeholders})"
_PASSAGE_BATCH = 500
_COUNT = "SELECT COUNT(*) FROM chunks"
_NEXT_RECORD_IDS = (
    "SELECT DISTINCT record_id FROM chunks WHERE ? IS NULL OR record_id > ? ORDER BY record_id LIMIT ?"
)
_RECORD_PASSAGES = (
    "SELECT record_id, text, metadata FROM chunks WHERE record_id IN ({placeholders})"
    " ORDER BY record_id, chunk_index"
)


class AsyncSqliteEmbeddingStore(AsyncEmbeddingStore):
    """Durable vector memory persisting unit-normalized float32 chunk vectors.

    Backed by the standard-library ``sqlite3`` driver run off the event loop, so
    it carries no third-party dependency. The single connection must never be
    used by two worker threads at once, so every operation holds an
    :class:`asyncio.Lock` until its thread finishes, even if the awaiting task
    is cancelled meanwhile. Each write is one transaction, rolled back on
    failure, and every SQLite failure (including a file that is not a
    database) surfaces as :class:`EmbeddingStoreError`, as does a file written
    by a newer sci-etl-core. The file records its schema version in
    ``PRAGMA user_version``.

    Similarity is a linear scan computed in NumPy: every stored vector is loaded
    and scored against the query in one matrix product, and only the best
    chunks' text and metadata are read. The decoded vectors stay in memory
    between queries and are reloaded only after a write, from this store or any
    other connection to the file, so repeated queries skip the read. This is
    exact and dependency-light, and fits
    corpora up to the low millions of chunks; swap in an ANN index behind this
    same interface if the memory outgrows a full scan.

    The file is opened, and its schema created, on first use. Use each instance
    from one event loop.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._runner = AsyncSqliteRunner(self._open_connection, error_factory=EmbeddingStoreError)
        self._vectors: _VectorSnapshot | None = None

    async def add(self, chunks: Sequence[EmbeddingChunk]) -> None:
        if not chunks:
            return
        rows = [self._to_row(chunk) for chunk in chunks]
        await self._runner.run(lambda connection: self._write(connection, None, rows), "write chunk embeddings")

    async def delete_record(self, record_id: str) -> None:
        await self._runner.run(lambda connection: self._write(connection, record_id, []), "delete chunk embeddings")

    async def replace_record(self, record_id: str, chunks: Sequence[EmbeddingChunk]) -> None:
        """Delete the record's chunks and insert ``chunks`` in one transaction."""
        rows = [self._to_row(chunk) for chunk in chunks]
        await self._runner.run(
            lambda connection: self._write(connection, record_id, rows), "replace chunk embeddings"
        )

    async def query(
        self,
        vector: Sequence[float],
        top_k: int = 5,
        min_score: float = -1.0,
        exclude_record_id: str | None = None,
    ) -> list[SearchHit]:
        if top_k <= 0:
            return []
        query_vector = unit_vector(vector)
        norm = float(np.linalg.norm(query_vector))
        if query_vector.size == 0 or norm == 0.0 or not np.isfinite(norm):
            return []
        return await self._runner.run(
            partial(
                self._select,
                query_vector=query_vector,
                top_k=top_k,
                min_score=min_score,
                exclude_record_id=exclude_record_id,
            ),
            "read chunk embeddings",
        )

    async def count(self) -> int:
        rows = await self._runner.run(
            lambda connection: connection.execute(_COUNT).fetchall(), "count chunk embeddings"
        )
        return int(rows[0][0])

    async def iter_records(self, batch_size: int = 100) -> AsyncIterator[StoredRecord]:
        """Yield every stored record's passages, reading ``batch_size`` records at a time.

        Each batch is read in one transaction and continues after the last
        ``record_id`` of the batch before, so records written during iteration
        are yielded when their id sorts after that point, and a record never
        repeats. No vector is loaded.

        Raises:
            ValueError: ``batch_size`` is less than 1.
            EmbeddingStoreError: The store cannot be read, or a chunk's metadata
                is not a JSON object.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        after: str | None = None
        while True:
            batch = await self._runner.run(
                partial(self._read_batch, after=after, batch_size=batch_size), "read stored passages"
            )
            if not batch:
                return
            for record in batch:
                yield record
            after = batch[-1].record_id

    async def aclose(self) -> None:
        """Close the connection; a later call transparently reopens it."""
        await self._runner.aclose()

    def _open_connection(self) -> sqlite3.Connection:
        self._vectors = None
        try:
            connection = sqlite3.connect(self._path, check_same_thread=False)
        except sqlite3.Error as exc:
            raise EmbeddingStoreError(f"Failed to open the SQLite embedding store: {exc}") from exc
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            migrate(connection, _MIGRATIONS, _newer_schema_error)
        except EmbeddingStoreError:
            connection.close()
            raise
        except sqlite3.Error as exc:
            connection.close()
            raise EmbeddingStoreError(f"Failed to open the SQLite embedding store: {exc}") from exc
        return connection

    def _write(self, connection: sqlite3.Connection, record_id: str | None, rows: list[tuple[Any, ...]]) -> None:
        self._vectors = None
        with connection:
            if record_id is not None:
                connection.execute(_DELETE, (record_id,))
            connection.executemany(_INSERT, rows)

    def _select(
        self,
        connection: sqlite3.Connection,
        query_vector: np.ndarray,
        top_k: int,
        min_score: float,
        exclude_record_id: str | None,
    ) -> list[SearchHit]:
        with connection:
            connection.execute("BEGIN")
            vectors = self._snapshot(connection, query_vector.size)
            if not vectors.rowids.size:
                return []
            scores = (vectors.matrix @ query_vector).astype(np.float64)
            usable = np.isfinite(scores) & (scores >= min_score)
            if exclude_record_id is not None:
                usable &= vectors.record_ids != exclude_record_id
            kept = np.flatnonzero(usable)
            ranked = kept[np.argsort(-scores[kept], kind="stable")][:top_k]
            passages = _read_passages(connection, [int(vectors.rowids[index]) for index in ranked])
        hits: list[SearchHit] = []
        for index in ranked:
            record_id, chunk_index, text, metadata = passages[int(vectors.rowids[index])]
            hits.append(SearchHit(record_id, chunk_index, text, float(scores[index]), json.loads(metadata)))
        return hits

    def _snapshot(self, connection: sqlite3.Connection, dim: int) -> _VectorSnapshot:
        version = int(connection.execute("PRAGMA data_version").fetchone()[0])
        cached = self._vectors
        if cached is not None and cached.version == version and cached.dim == dim:
            return cached
        rows = connection.execute(_SELECT_VECTORS, (dim,)).fetchall()
        blobs = [blob for _rowid, _record_id, blob in rows]
        self._vectors = _VectorSnapshot(
            version=version,
            dim=dim,
            rowids=np.array([rowid for rowid, _record_id, _blob in rows], dtype=np.int64),
            record_ids=np.array([record_id for _rowid, record_id, _blob in rows], dtype=object),
            matrix=np.vstack([np.frombuffer(blob, dtype=np.float32) for blob in blobs])
            if blobs
            else np.empty((0, dim), dtype=np.float32),
        )
        return self._vectors

    @staticmethod
    def _read_batch(connection: sqlite3.Connection, after: str | None, batch_size: int) -> list[StoredRecord]:
        with connection:
            connection.execute("BEGIN")
            record_ids = [row[0] for row in connection.execute(_NEXT_RECORD_IDS, (after, after, batch_size)).fetchall()]
            if not record_ids:
                return []
            rows = connection.execute(
                _RECORD_PASSAGES.format(placeholders=", ".join("?" * len(record_ids))), record_ids
            ).fetchall()
        passages: dict[str, list[str]] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for record_id, text, encoded in rows:
            passages.setdefault(record_id, []).append(text)
            if record_id not in metadata:
                metadata[record_id] = _decode_metadata(encoded)
        return [StoredRecord(record_id, tuple(passages[record_id]), metadata[record_id]) for record_id in passages]

    @staticmethod
    def _to_row(chunk: EmbeddingChunk) -> tuple[Any, ...]:
        vector = unit_vector(chunk.vector).astype(np.float32)
        return (
            chunk.record_id,
            chunk.chunk_index,
            chunk.text,
            int(vector.size),
            vector.tobytes(),
            json.dumps(chunk.metadata),
        )


@dataclass(frozen=True)
class _VectorSnapshot:
    version: int
    dim: int
    rowids: np.ndarray
    record_ids: np.ndarray
    matrix: np.ndarray


def _read_passages(connection: sqlite3.Connection, rowids: list[int]) -> dict[int, tuple[Any, ...]]:
    passages: dict[int, tuple[Any, ...]] = {}
    for start in range(0, len(rowids), _PASSAGE_BATCH):
        batch = rowids[start : start + _PASSAGE_BATCH]
        query = _SELECT_PASSAGES.format(placeholders=", ".join("?" * len(batch)))
        for rowid, *passage in connection.execute(query, batch).fetchall():
            passages[rowid] = tuple(passage)
    return passages


def _newer_schema_error(found: int, supported: int) -> EmbeddingStoreError:
    return EmbeddingStoreError(newer_schema_message("embedding store", found, supported))


def _decode_metadata(text: str) -> dict[str, Any]:
    try:
        metadata = json.loads(text)
    except ValueError:
        metadata = None
    if not isinstance(metadata, dict):
        raise EmbeddingStoreError(f"A stored chunk's metadata is not a JSON object: {text[:80]!r}")
    return metadata
