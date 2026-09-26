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


class TestAsyncSqliteEmbeddingStoreVectorCache:
    @pytest.mark.asyncio
    async def test_own_writes_are_seen_by_later_queries(self, tmp_path):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            await store.add([_chunk("a", 0, "first", [1.0, 0.0])])
            assert [hit.record_id for hit in await store.query([1.0, 0.0])] == ["a"]
            await store.add([_chunk("b", 0, "second", [1.0, 0.1])])
            assert [hit.record_id for hit in await store.query([1.0, 0.0])] == ["a", "b"]
            await store.delete_record("a")
            assert [hit.record_id for hit in await store.query([1.0, 0.0])] == ["b"]
            await store.replace_record("b", [_chunk("b", 0, "replaced", [0.0, 1.0])])
            hits = await store.query([0.0, 1.0])
            assert [(hit.record_id, hit.text) for hit in hits] == [("b", "replaced")]
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_writes_from_another_connection_are_seen(self, tmp_path):
        reader = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        writer = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            await writer.add([_chunk("a", 0, "first", [1.0, 0.0])])
            assert [hit.record_id for hit in await reader.query([1.0, 0.0])] == ["a"]
            await writer.add([_chunk("b", 0, "second", [1.0, 0.1])])
            assert [hit.record_id for hit in await reader.query([1.0, 0.0])] == ["a", "b"]
            await writer.delete_record("a")
            assert [hit.record_id for hit in await reader.query([1.0, 0.0])] == ["b"]
        finally:
            await reader.aclose()
            await writer.aclose()

    @pytest.mark.asyncio
    async def test_cached_vectors_honor_each_query_arguments(self, tmp_path):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            await store.add(
                [
                    _chunk("a", 0, "a0", [1.0, 0.0]),
                    _chunk("a", 1, "a1", [0.9, 0.1]),
                    _chunk("b", 0, "b0", [0.0, 1.0]),
                    _chunk("c", 0, "c0", [1.0, 0.0, 0.0]),
                ]
            )
            assert [hit.text for hit in await store.query([1.0, 0.0])] == ["a0", "a1", "b0"]
            assert [hit.text for hit in await store.query([1.0, 0.0], exclude_record_id="a")] == ["b0"]
            assert [hit.text for hit in await store.query([1.0, 0.0], top_k=1)] == ["a0"]
            assert [hit.text for hit in await store.query([1.0, 0.0], min_score=0.5)] == ["a0", "a1"]
            assert [hit.text for hit in await store.query([1.0, 0.0, 0.0])] == ["c0"]
            assert [hit.text for hit in await store.query([1.0, 0.0])] == ["a0", "a1", "b0"]
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_empty_store_returns_no_hits(self, tmp_path):
        store = AsyncSqliteEmbeddingStore(tmp_path / "memory.db")
        try:
            assert await store.query([1.0, 0.0]) == []
        finally:
            await store.aclose()


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
