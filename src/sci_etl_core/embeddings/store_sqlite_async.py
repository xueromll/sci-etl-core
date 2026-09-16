from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Sequence
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.embeddings._similarity import unit_vector
from sci_etl_core.embeddings.store_base import (
    AsyncEmbeddingStore,
    EmbeddingChunk,
    SearchHit,
    StoredRecord,
)
from sci_etl_core.exceptions import EmbeddingStoreError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    record_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (record_id, chunk_index)
);
"""
_INSERT = (
    "INSERT OR REPLACE INTO chunks (record_id, chunk_index, text, dim, vector, metadata)"
    " VALUES (?, ?, ?, ?, ?, ?)"
)
_DELETE = "DELETE FROM chunks WHERE record_id = ?"
_SELECT = "SELECT record_id, chunk_index, text, dim, vector, metadata FROM chunks"
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
    database) surfaces as :class:`EmbeddingStoreError`.

    Similarity is a linear scan computed in NumPy: every stored vector is loaded
    and dotted against the query. This is exact and dependency-light, and fits
    corpora up to the low millions of chunks; swap in an ANN index behind this
    same interface if the memory outgrows a full scan.

    The file is opened, and its schema created, on first use. Use each instance
    from one event loop.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._runner = AsyncSqliteRunner(self._open_connection, error_factory=EmbeddingStoreError)

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
        rows = await self._runner.run(
            lambda connection: self._select(connection, exclude_record_id), "read chunk embeddings"
        )
        hits = [hit for hit in self._score_rows(rows, query_vector) if hit.score >= min_score]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

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
        try:
            connection = sqlite3.connect(self._path, check_same_thread=False)
        except sqlite3.Error as exc:
            raise EmbeddingStoreError(f"Failed to open the SQLite embedding store: {exc}") from exc
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            connection.close()
            raise EmbeddingStoreError(f"Failed to open the SQLite embedding store: {exc}") from exc
        return connection

    @staticmethod
    def _write(connection: sqlite3.Connection, record_id: str | None, rows: list[tuple[Any, ...]]) -> None:
        with connection:
            if record_id is not None:
                connection.execute(_DELETE, (record_id,))
            connection.executemany(_INSERT, rows)

    @staticmethod
    def _select(connection: sqlite3.Connection, exclude_record_id: str | None) -> list[tuple[Any, ...]]:
        if exclude_record_id is None:
            return connection.execute(_SELECT).fetchall()
        return connection.execute(f"{_SELECT} WHERE record_id != ?", (exclude_record_id,)).fetchall()

    @staticmethod
    def _score_rows(
        rows: list[tuple[Any, ...]], query_vector: np.ndarray
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for record_id, chunk_index, text, dim, blob, metadata in rows:
            if dim != query_vector.size:
                continue
            stored = np.frombuffer(blob, dtype=np.float32)
            score = float(stored @ query_vector)
            if not np.isfinite(score):
                continue
            hits.append(
                SearchHit(record_id, chunk_index, text, score, json.loads(metadata))
            )
        return hits

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


def _decode_metadata(text: str) -> dict[str, Any]:
    try:
        metadata = json.loads(text)
    except ValueError:
        metadata = None
    if not isinstance(metadata, dict):
        raise EmbeddingStoreError(f"A stored chunk's metadata is not a JSON object: {text[:80]!r}")
    return metadata
