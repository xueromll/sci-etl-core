from __future__ import annotations

from typing import Any

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, SearchHit


class AsyncSimilarArticleFinder:
    """Search the accumulated memory for passages resembling a piece of text."""

    def __init__(self, embedder: AsyncEmbedder, store: AsyncEmbeddingStore) -> None:
        self._embedder = embedder
        self._store = store

    async def find_similar_chunks(
        self,
        text: str,
        top_k: int = 5,
        min_score: float = 0.0,
        exclude_record_id: str | None = None,
    ) -> list[SearchHit]:
        vectors = await self._embedder.embed([text])
        if not vectors:
            return []
        return await self._store.query(vectors[0], top_k, min_score, exclude_record_id)

    async def find_similar_articles(
        self,
        text: str,
        top_k: int = 5,
        min_score: float = 0.0,
        exclude_record_id: str | None = None,
        chunk_pool: int = 50,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Rank whole articles, scoring each by its single best-matching chunk."""
        hits = await self.find_similar_chunks(text, chunk_pool, min_score, exclude_record_id)
        best: dict[str, tuple[float, dict[str, Any]]] = {}
        for hit in hits:
            if hit.record_id not in best or hit.score > best[hit.record_id][0]:
                best[hit.record_id] = (hit.score, hit.metadata)
        ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
        return [(record_id, score, metadata) for record_id, (score, metadata) in ranked[:top_k]]
