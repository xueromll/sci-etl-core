from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from sci_etl_core.embeddings.store_base import EmbeddingChunk
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.search.edges import EmbeddingEdgeSource, MetadataEdgeSource
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_memory import InMemoryTextSearchStore
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store

TAGGED = [
    SearchDocument("p1", title="One", metadata={"categories": ["GA", "CO"], "authors": ["A"]}),
    SearchDocument("p2", title="Two", metadata={"categories": ["GA"], "authors": ["A", "B"]}),
    SearchDocument("p3", title="Three", metadata={"categories": ["HE"], "authors": ["C"]}),
    SearchDocument("p4", title="Four", metadata={"categories": ["CO"]}),
    SearchDocument("p5", title="Five"),
]


@asynccontextmanager
async def tagged_store(kind, directory):
    options = {"facet_keys": ("categories", "authors")}
    if kind == "memory":
        store = InMemoryTextSearchStore(**options)
    else:
        store = AsyncSqliteFts5Store(directory / "search.db", **options)
    try:
        await store.index(TAGGED)
        yield store
    finally:
        await store.aclose()


@pytest.mark.parametrize("kind", ["memory", "fts5"])
class TestMetadataEdgeSource:
    @pytest.mark.asyncio
    async def test_weights_are_the_jaccard_index_of_shared_tags(self, kind, tmp_path):
        async with tagged_store(kind, tmp_path) as store:
            source = MetadataEdgeSource(store)
            assert source.kind == "metadata"
            assert await source.neighbours(["p1", "p3", "p5", "unknown", "p1"], 8) == {
                "p1": [("p2", 0.5), ("p4", pytest.approx(1 / 3))],
                "p3": [],
                "p5": [],
                "unknown": [],
            }

    @pytest.mark.asyncio
    async def test_limit_cuts_each_list_and_a_limit_below_one_returns_empty_lists(self, kind, tmp_path):
        async with tagged_store(kind, tmp_path) as store:
            source = MetadataEdgeSource(store, keys=["categories"])
            assert await source.neighbours(["p1"], 1) == {"p1": [("p2", 0.5)]}
            assert await source.neighbours(["p1", "p2"], 0) == {"p1": [], "p2": []}
            assert await source.neighbours([], 5) == {}


class TestMetadataEdgeSourceConfiguration:
    def test_keys_must_be_facet_keys_of_the_store(self):
        with pytest.raises(ValueError, match="'authors' is not a facet key"):
            MetadataEdgeSource(InMemoryTextSearchStore(facet_keys=("categories",)))

    def test_at_least_one_key_is_required(self):
        with pytest.raises(ValueError, match="needs at least one key"):
            MetadataEdgeSource(InMemoryTextSearchStore(facet_keys=("categories",)), keys=())


class TableEmbedder:
    def __init__(self, table, drop_one=False):
        self.table = table
        self.drop_one = drop_one
        self.calls = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        vectors = [self.table[text] for text in texts]
        return vectors[1:] if self.drop_one else vectors


async def semantic_fixture(embedder_table=None, drop_one=False):
    text_store = InMemoryTextSearchStore()
    await text_store.index(
        [
            SearchDocument("r1", title="Dwarf galaxies", abstract="Photometry"),
            SearchDocument("r2", title="Streams", abstract="  "),
            SearchDocument("r3", title=" ", abstract=""),
        ]
    )
    vectors = InMemoryEmbeddingStore()
    await vectors.add(
        [
            EmbeddingChunk("r1", 0, "chunk", [1.0, 0.0]),
            EmbeddingChunk("r1", 1, "chunk", [0.5, 0.5]),
            EmbeddingChunk("r2", 0, "chunk", [0.8, 0.6]),
            EmbeddingChunk("r3", 0, "chunk", [0.0, 1.0]),
            EmbeddingChunk("r5", 0, "chunk", [0.9, 0.1]),
            EmbeddingChunk("r6", 0, "chunk", [-1.0, 0.0]),
        ]
    )
    table = embedder_table or {"Dwarf galaxies\n\nPhotometry": [1.0, 0.0], "Streams": [0.8, 0.6]}
    embedder = TableEmbedder(table, drop_one=drop_one)
    return embedder, vectors, text_store


class TestEmbeddingEdgeSource:
    @pytest.mark.asyncio
    async def test_a_batch_is_embedded_once_and_each_record_keeps_its_best_chunk_per_neighbour(self, mocker):
        embedder, vectors, text_store = await semantic_fixture()
        query = mocker.spy(vectors, "query")
        source = EmbeddingEdgeSource(embedder, vectors, text_store, chunk_pool_factor=3)
        assert source.kind == "semantic"
        neighbours = await source.neighbours(["r1", "r2", "r3", "r4", "r1"], 2)
        assert embedder.calls == [["Dwarf galaxies\n\nPhotometry", "Streams"]]
        assert neighbours == {
            "r1": [("r5", pytest.approx(0.9939, abs=1e-4)), ("r2", pytest.approx(0.8))],
            "r2": [("r1", pytest.approx(0.9899, abs=1e-4)), ("r5", pytest.approx(0.8614, abs=1e-4))],
            "r3": [],
            "r4": [],
        }
        assert [call.args[1:] for call in query.call_args_list] == [(6, 0.0, "r1"), (6, 0.0, "r2")]

    @pytest.mark.asyncio
    async def test_nothing_is_embedded_when_no_record_has_text(self):
        embedder, vectors, text_store = await semantic_fixture()
        source = EmbeddingEdgeSource(embedder, vectors, text_store)
        assert await source.neighbours(["r3", "missing"], 5) == {"r3": [], "missing": []}
        assert await source.neighbours(["r1"], 0) == {"r1": []}
        assert await source.neighbours([], 5) == {}
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_an_embedder_returning_the_wrong_number_of_vectors_raises(self):
        embedder, vectors, text_store = await semantic_fixture(drop_one=True)
        with pytest.raises(EmbeddingError, match="Embedder returned 1 vectors for 2 texts"):
            await EmbeddingEdgeSource(embedder, vectors, text_store).neighbours(["r1", "r2"], 3)

    def test_a_chunk_pool_factor_below_one_is_rejected(self):
        stores = (InMemoryEmbeddingStore(), InMemoryTextSearchStore())
        with pytest.raises(ValueError, match="chunk_pool_factor must be at least 1"):
            EmbeddingEdgeSource(TableEmbedder({}), *stores, chunk_pool_factor=0)
