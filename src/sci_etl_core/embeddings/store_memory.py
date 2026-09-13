from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from sci_etl_core.embeddings._similarity import unit_vector
from sci_etl_core.embeddings.store_base import (
    AsyncEmbeddingStore,
    EmbeddingChunk,
    SearchHit,
)


class _Row:
    __slots__ = ("record_id", "chunk_index", "text", "vector", "metadata")

    def __init__(self, chunk: EmbeddingChunk) -> None:
        self.record_id = chunk.record_id
        self.chunk_index = chunk.chunk_index
        self.text = chunk.text
        self.vector = unit_vector(chunk.vector)
        self.metadata = dict(chunk.metadata)


class InMemoryEmbeddingStore(AsyncEmbeddingStore):
    """Non-persistent store backed by a dict. Vectors are unit-normalized.

    Chunks are keyed by ``(record_id, chunk_index)`` so that re-adding an
    article replaces its earlier chunks instead of accumulating duplicates.
    That mirrors the primary key of the durable SQLite store, keeping the two
    backends interchangeable: re-ingesting a record must not silently give it
    extra weight in one of them.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, int], _Row] = {}

    async def add(self, chunks: Sequence[EmbeddingChunk]) -> None:
        for chunk in chunks:
            self._rows[(chunk.record_id, chunk.chunk_index)] = _Row(chunk)

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
        candidates = [
            row
            for row in self._rows.values()
            if row.vector.size == query_vector.size
            and (exclude_record_id is None or row.record_id != exclude_record_id)
        ]
        if not candidates:
            return []
        scores = np.vstack([row.vector for row in candidates]) @ query_vector
        hits: list[SearchHit] = []
        for index in np.argsort(scores)[::-1]:
            score = float(scores[index])
            if score < min_score:
                break
            row = candidates[index]
            hits.append(SearchHit(row.record_id, row.chunk_index, row.text, score, dict(row.metadata)))
            if len(hits) >= top_k:
                break
        return hits

    async def count(self) -> int:
        return len(self._rows)
