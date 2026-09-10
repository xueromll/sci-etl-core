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
    """Non-persistent store backed by a plain list. Vectors are unit-normalized."""

    def __init__(self) -> None:
        self._rows: list[_Row] = []

    async def add(self, chunks: Sequence[EmbeddingChunk]) -> None:
        self._rows.extend(_Row(chunk) for chunk in chunks)

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
        candidates = [
            row
            for row in self._rows
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
