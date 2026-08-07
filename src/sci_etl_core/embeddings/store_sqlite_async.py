from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from sci_etl_core.embeddings._similarity import unit_vector
from sci_etl_core.embeddings.store_base import (
    AsyncEmbeddingStore,
    EmbeddingChunk,
    SearchHit,
)
from sci_etl_core.exceptions import EmbeddingStoreError

T = TypeVar("T")

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
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def add(self, chunks: Sequence[EmbeddingChunk]) -> None:
        if not chunks:
            return
        rows = [self._to_row(chunk) for chunk in chunks]
        await self._run(lambda connection: self._write(connection, None, rows), "write chunk embeddings")

    async def delete_record(self, record_id: str) -> None:
        await self._run(lambda connection: self._write(connection, record_id, []), "delete chunk embeddings")

    async def replace_record(self, record_id: str, chunks: Sequence[EmbeddingChunk]) -> None:
        """Delete the record's chunks and insert ``chunks`` in one transaction."""
        rows = [self._to_row(chunk) for chunk in chunks]
        await self._run(
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
        rows = await self._run(
            lambda connection: self._select(connection, exclude_record_id), "read chunk embeddings"
        )
        hits = [hit for hit in self._score_rows(rows, query_vector) if hit.score >= min_score]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    async def count(self) -> int:
        rows = await self._run(lambda connection: connection.execute(_COUNT).fetchall(), "count chunk embeddings")
        return int(rows[0][0])

    async def aclose(self) -> None:
        async with self._lock:
            connection, self._connection = self._connection, None
        if connection is not None:
            await asyncio.to_thread(connection.close)

    async def _run(self, operation: Callable[[sqlite3.Connection], T], action: str) -> T:
        async with self._lock:
            work = asyncio.ensure_future(asyncio.to_thread(self._execute, operation))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                await asyncio.wait({work})
                if not work.cancelled():
                    work.exception()
                raise
            except sqlite3.Error as exc:
                raise EmbeddingStoreError(f"Failed to {action}: {exc}") from exc

    def _execute(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        return operation(self._connect())

    def _connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
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
        self._connection = connection
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
