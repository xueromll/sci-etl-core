from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

import pytest

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.chunking import SlidingWindowChunker
from sci_etl_core.embeddings.finder_async import AsyncSimilarArticleFinder
from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, EmbeddingChunk, SearchHit, StoredRecord
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.exceptions import EmbeddingStoreError

BACKENDS = ["memory", "sqlite"]


@asynccontextmanager
async def open_store(kind, directory):
    store = InMemoryEmbeddingStore() if kind == "memory" else AsyncSqliteEmbeddingStore(directory / "memory.db")
    try:
        yield store
    finally:
        await store.aclose()


def chunk(record_id, index, vector=(1.0, 0.0), **metadata):
    return EmbeddingChunk(record_id, index, f"{record_id}-{index}", list(vector), metadata)


async def collected(store, batch_size=100):
    return [record async for record in store.iter_records(batch_size)]


@pytest.mark.parametrize("kind", BACKENDS)
class TestIterRecords:
    @pytest.mark.asyncio
    async def test_yields_each_record_once_in_id_order_with_passages_in_chunk_order(self, kind, tmp_path):
        chunks = [
            chunk(record_id, index, title=record_id, position=index) for record_id in "bca" for index in (2, 0, 1)
        ]
        async with open_store(kind, tmp_path) as store:
            await store.add([*chunks, chunk("", 0, title="")])
            for batch_size in (1, 2, 100):
                assert await collected(store, batch_size) == [
                    StoredRecord("", ("-0",), {"title": ""}),
                    StoredRecord("a", ("a-0", "a-1", "a-2"), {"title": "a", "position": 0}),
                    StoredRecord("b", ("b-0", "b-1", "b-2"), {"title": "b", "position": 0}),
                    StoredRecord("c", ("c-0", "c-1", "c-2"), {"title": "c", "position": 0}),
                ]

    @pytest.mark.asyncio
    async def test_an_empty_store_yields_nothing(self, kind, tmp_path):
        async with open_store(kind, tmp_path) as store:
            assert await collected(store) == []

    @pytest.mark.asyncio
    async def test_a_batch_size_below_one_is_rejected(self, kind, tmp_path):
        async with open_store(kind, tmp_path) as store:
            with pytest.raises(ValueError, match="batch_size must be a positive integer"):
                await collected(store, 0)


@pytest.mark.asyncio
async def test_the_sqlite_store_continues_after_the_last_record_of_a_batch_written_during_iteration(tmp_path):
    async with open_store("sqlite", tmp_path) as store:
        await store.add([chunk("a", 0), chunk("c", 0)])
        seen = []
        async for record in store.iter_records(1):
            seen.append(record.record_id)
            if record.record_id == "a":
                await store.add([chunk("b", 0), chunk("0", 0)])
        assert seen == ["a", "b", "c"]


@pytest.mark.parametrize("metadata", ["not json", "[1]"])
@pytest.mark.asyncio
async def test_unreadable_chunk_metadata_is_a_store_error(tmp_path, metadata):
    async with open_store("sqlite", tmp_path) as store:
        await store.add([chunk("a", 0)])
        await store.aclose()
        connection = sqlite3.connect(tmp_path / "memory.db")
        with connection:
            connection.execute("UPDATE chunks SET metadata = ?", (metadata,))
        connection.close()
        with pytest.raises(EmbeddingStoreError, match="A stored chunk's metadata is not a JSON object"):
            await collected(store)


def test_a_store_that_cannot_enumerate_its_records_says_so():
    class VectorsOnly(AsyncEmbeddingStore):
        async def add(self, chunks):
            return None

        async def delete_record(self, record_id):
            return None

        async def query(self, vector, top_k=5, min_score=-1.0, exclude_record_id=None):
            return []

        async def count(self):
            return 0

    with pytest.raises(NotImplementedError, match="VectorsOnly cannot enumerate its stored records"):
        VectorsOnly().iter_records()


class Table(AsyncEmbedder):
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class TestFindBestChunks:
    @pytest.mark.asyncio
    async def test_returns_each_records_best_chunk_with_its_text(self):
        store = InMemoryEmbeddingStore()
        await store.add(
            [
                chunk("a", 0, (0.6, 0.8), title="A"),
                chunk("a", 1, (1.0, 0.0), title="A"),
                chunk("b", 0, (0.8, 0.6), title="B"),
            ]
        )
        finder = AsyncSimilarArticleFinder(Table(), store)
        best = await finder.find_best_chunks("q", top_k=5)
        assert [(hit.record_id, hit.chunk_index, hit.text) for hit in best] == [("a", 1, "a-1"), ("b", 0, "b-0")]
        assert best[0] == SearchHit("a", 1, "a-1", pytest.approx(1.0), {"title": "A"})
        assert await finder.find_similar_articles("q", top_k=1) == [("a", pytest.approx(1.0), {"title": "A"})]


def test_the_sliding_window_chunker_reports_its_window_and_overlap():
    assert (SlidingWindowChunker().chunk_words, SlidingWindowChunker().overlap_words) == (350, 50)
    assert (SlidingWindowChunker(10).chunk_words, SlidingWindowChunker(10).overlap_words) == (10, 9)
