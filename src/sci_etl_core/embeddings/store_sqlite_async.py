from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from sci_etl_core.embeddings._similarity import unit_vector
from sci_etl_core.embeddings.store_base import (
    AsyncEmbeddingStore,
    EmbeddingChunk,
    SearchHit,
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


class AsyncSqliteEmbeddingStore(AsyncEmbeddingStore):
    """Durable vector memory persisting unit-normalized float32 chunk vectors.

    Similarity is a linear scan computed in NumPy: every stored vector is
    loaded and dotted against the query. This is exact and dependency-light,
    and fits corpora up to the low millions of chunks; swap in an ANN index
    behind this same interface if the memory outgrows a full scan.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._db: Any = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> Any:
        if self._db is None:
            async with self._lock:
                if self._db is None:
                    try:
                        import aiosqlite
                    except ImportError as exc:
                        raise EmbeddingStoreError(
                            "aiosqlite is required for the SQLite embedding store"
                        ) from exc
                    self._db = await aiosqlite.connect(self._path)
                    await self._db.execute("PRAGMA journal_mode=WAL")
                    await self._db.executescript(_SCHEMA)
                    await self._db.commit()
        return self._db

    async def add(self, chunks: Sequence[EmbeddingChunk]) -> None:
        if not chunks:
            return
        rows = [self._to_row(chunk) for chunk in chunks]
        db = await self._connect()
        try:
            await db.executemany(
                "INSERT OR REPLACE INTO chunks"
                " (record_id, chunk_index, text, dim, vector, metadata)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise EmbeddingStoreError(f"Failed to write chunk embeddings: {exc}") from exc

    async def query(
        self,
        vector: Sequence[float],
        top_k: int = 5,
        min_score: float = -1.0,
        exclude_record_id: str | None = None,
    ) -> list[SearchHit]:
        query_vector = unit_vector(vector)
        if query_vector.size == 0 or float(np.linalg.norm(query_vector)) == 0.0:
            return []
        rows = await self._fetch_rows(exclude_record_id)
        scored = self._score_rows(rows, query_vector)
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return [hit for hit in scored if hit.score >= min_score][:top_k]

    async def count(self) -> int:
        db = await self._connect()
        async with db.execute("SELECT COUNT(*) FROM chunks") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _fetch_rows(self, exclude_record_id: str | None) -> list[tuple[Any, ...]]:
        db = await self._connect()
        sql = "SELECT record_id, chunk_index, text, dim, vector, metadata FROM chunks"
        params: tuple[Any, ...] = ()
        if exclude_record_id is not None:
            sql += " WHERE record_id != ?"
            params = (exclude_record_id,)
        async with db.execute(sql, params) as cursor:
            return await cursor.fetchall()

    @staticmethod
    def _score_rows(rows: list[tuple[Any, ...]], query_vector: np.ndarray) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for record_id, chunk_index, text, dim, blob, metadata in rows:
            if dim != query_vector.size:
                continue
            stored = np.frombuffer(blob, dtype=np.float32)
            score = float(stored @ query_vector)
            hits.append(SearchHit(record_id, chunk_index, text, score, json.loads(metadata)))
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
