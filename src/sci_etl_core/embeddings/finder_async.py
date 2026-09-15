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
        """Return up to ``top_k`` stored chunks most similar to ``text``, best first.

        ``text`` is embedded in one call, and the other arguments are those of
        :meth:`~sci_etl_core.embeddings.store_base.AsyncEmbeddingStore.query`,
        except that ``min_score`` defaults to 0. An embedder that returns no
        vector gives no hits.
        """
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
        """Rank whole articles, scoring each by its single best-matching chunk.

        The ``chunk_pool`` best chunks are collapsed to one entry per record, so
        at most ``chunk_pool`` records come back, and often far fewer when long
        articles own many of those chunks; raise ``chunk_pool`` along with
        ``top_k``. Each entry is ``(record_id, score, metadata)``, where
        ``metadata`` is the best chunk's; the chunk's text is not returned.
        """
        hits = await self.find_similar_chunks(text, chunk_pool, min_score, exclude_record_id)
        best: dict[str, tuple[float, dict[str, Any]]] = {}
        for hit in hits:
            if hit.record_id not in best or hit.score > best[hit.record_id][0]:
                best[hit.record_id] = (hit.score, hit.metadata)
        ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
        return [(record_id, score, metadata) for record_id, (score, metadata) in ranked[:top_k]]
