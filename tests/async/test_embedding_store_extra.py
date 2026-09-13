from __future__ import annotations

import pytest

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.finder_async import AsyncSimilarArticleFinder
from sci_etl_core.embeddings.store_base import EmbeddingChunk
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.exceptions import EmbeddingStoreError


class _EmptyEmbedder(AsyncEmbedder):
    async def embed(self, texts):
        return []


def _chunk(record_id: str, index: int, text: str, vector):
    return EmbeddingChunk(record_id, index, text, vector, {"title": record_id})


class TestAsyncSqliteEmbeddingStoreOpenFailure:
    @pytest.mark.asyncio
    async def test_open_failure_is_typed(self, tmp_path):
        store = AsyncSqliteEmbeddingStore(tmp_path)  # a directory, not a file
        with pytest.raises(EmbeddingStoreError, match="Failed to open"):
            await store.count()


class TestInMemoryEmbeddingStoreEdges:
    @pytest.mark.asyncio
    async def test_query_with_no_candidates_returns_empty(self):
        store = InMemoryEmbeddingStore()
        await store.add([_chunk("a", 0, "only", [1.0, 0.0])])
        assert await store.query([1.0, 0.0], exclude_record_id="a") == []

    @pytest.mark.asyncio
    async def test_default_aclose_is_a_noop(self):
        store = InMemoryEmbeddingStore()
        assert await store.aclose() is None


class TestAsyncSimilarArticleFinderEmpty:
    @pytest.mark.asyncio
    async def test_no_embedding_yields_no_hits(self):
        finder = AsyncSimilarArticleFinder(_EmptyEmbedder(), InMemoryEmbeddingStore())
        assert await finder.find_similar_chunks("anything") == []
