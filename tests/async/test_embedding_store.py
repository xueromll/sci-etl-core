from __future__ import annotations

import pytest

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.chunking import SlidingWindowChunker
from sci_etl_core.embeddings.finder_async import AsyncSimilarArticleFinder
from sci_etl_core.embeddings.ingest_async import AsyncChunkIngestor
from sci_etl_core.embeddings.store_base import EmbeddingChunk
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.exceptions import EmbeddingStoreError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.state.async_base import AsyncStateManager


class _FakeEmbedder(AsyncEmbedder):
    def __init__(self, table):
        self._table = table
        self.calls = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [self._table[text] for text in texts]


def _chunks(*specs):
    return [
        EmbeddingChunk(rid, idx, text, vec, {"title": rid})
        for rid, idx, text, vec in specs
    ]


class TestSlidingWindowChunker:
    def test_empty_text_yields_nothing(self):
        assert SlidingWindowChunker().chunk("   ") == []

    def test_short_text_is_one_chunk(self):
        assert SlidingWindowChunker(chunk_words=10).chunk("a b c") == ["a b c"]

    def test_windows_overlap_and_cover(self):
        words = " ".join(str(n) for n in range(10))
        chunks = SlidingWindowChunker(chunk_words=4, overlap_words=1).chunk(words)
        assert chunks[0] == "0 1 2 3"
        assert chunks[1] == "3 4 5 6"
        assert chunks[-1].split()[-1] == "9"

    def test_rejects_bad_overlap(self):
        with pytest.raises(ValueError):
            SlidingWindowChunker(chunk_words=4, overlap_words=4)

    def test_rejects_non_positive_size(self):
        with pytest.raises(ValueError):
            SlidingWindowChunker(chunk_words=0)


class TestInMemoryEmbeddingStore:
    @pytest.mark.asyncio
    async def test_add_and_count(self):
        store = InMemoryEmbeddingStore()
        await store.add(_chunks(("a", 0, "x", [1.0, 0.0]), ("a", 1, "y", [0.0, 1.0])))
        assert await store.count() == 2

    @pytest.mark.asyncio
    async def test_query_ranks_by_similarity(self):
        store = InMemoryEmbeddingStore()
        await store.add(_chunks(("a", 0, "near", [1.0, 0.0]), ("b", 0, "far", [0.0, 1.0])))
        hits = await store.query([0.9, 0.1], top_k=2)
        assert [hit.record_id for hit in hits] == ["a", "b"]
        assert hits[0].score > hits[1].score

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self):
        store = InMemoryEmbeddingStore()
        await store.add(_chunks(("a", 0, "x", [1.0, 0.0]), ("b", 0, "y", [0.9, 0.1])))
        assert len(await store.query([1.0, 0.0], top_k=1)) == 1

    @pytest.mark.asyncio
    async def test_min_score_filters(self):
        store = InMemoryEmbeddingStore()
        await store.add(_chunks(("a", 0, "orthogonal", [0.0, 1.0])))
        assert await store.query([1.0, 0.0], min_score=0.5) == []

    @pytest.mark.asyncio
    async def test_exclude_record_id(self):
        store = InMemoryEmbeddingStore()
        await store.add(_chunks(("a", 0, "self", [1.0, 0.0]), ("b", 0, "other", [1.0, 0.0])))
        hits = await store.query([1.0, 0.0], exclude_record_id="a")
        assert [hit.record_id for hit in hits] == ["b"]

    @pytest.mark.asyncio
    async def test_empty_query_returns_nothing(self):
        store = InMemoryEmbeddingStore()
        await store.add(_chunks(("a", 0, "x", [1.0, 0.0])))
        assert await store.query([]) == []


class TestAsyncSqliteEmbeddingStore:
    @pytest.fixture
    def path(self, tmp_path):
        return tmp_path / "memory.db"

    @pytest.mark.asyncio
    async def test_persists_across_reopen(self, path):
        store = AsyncSqliteEmbeddingStore(path)
        await store.add(_chunks(("a", 0, "hello", [1.0, 0.0]), ("b", 0, "world", [0.0, 1.0])))
        await store.aclose()

        reopened = AsyncSqliteEmbeddingStore(path)
        try:
            assert await reopened.count() == 2
            hits = await reopened.query([1.0, 0.0], top_k=1)
            assert hits[0].record_id == "a"
            assert hits[0].text == "hello"
            assert hits[0].metadata == {"title": "a"}
        finally:
            await reopened.aclose()

    @pytest.mark.asyncio
    async def test_reingest_replaces_same_chunk(self, path):
        store = AsyncSqliteEmbeddingStore(path)
        try:
            await store.add(_chunks(("a", 0, "first", [1.0, 0.0])))
            await store.add(_chunks(("a", 0, "second", [0.0, 1.0])))
            assert await store.count() == 1
            hits = await store.query([0.0, 1.0], top_k=1)
            assert hits[0].text == "second"
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_exclude_and_min_score(self, path):
        store = AsyncSqliteEmbeddingStore(path)
        try:
            await store.add(
                _chunks(("a", 0, "self", [1.0, 0.0]), ("b", 0, "match", [1.0, 0.0]))
            )
            hits = await store.query([1.0, 0.0], exclude_record_id="a", min_score=0.5)
            assert [hit.record_id for hit in hits] == ["b"]
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_add_empty_is_noop(self, path):
        store = AsyncSqliteEmbeddingStore(path)
        try:
            await store.add([])
            assert await store.count() == 0
        finally:
            await store.aclose()


class TestAsyncChunkIngestor:
    @pytest.mark.asyncio
    async def test_chunks_embeds_and_stores(self):
        embedder = _FakeEmbedder({"one two": [1.0, 0.0], "two three": [0.0, 1.0]})
        store = InMemoryEmbeddingStore()
        ingestor = AsyncChunkIngestor(
            SlidingWindowChunker(chunk_words=2, overlap_words=1), embedder, store
        )
        record = RawRecord("a", "Title", "abstract", source_url="http://x")
        stored = await ingestor.ingest(record, "one two three")
        assert stored == 2
        assert await store.count() == 2
        hits = await store.query([1.0, 0.0], top_k=1)
        assert hits[0].metadata == {"title": "Title", "source_url": "http://x"}

    @pytest.mark.asyncio
    async def test_empty_text_stores_nothing(self):
        embedder = _FakeEmbedder({})
        store = InMemoryEmbeddingStore()
        ingestor = AsyncChunkIngestor(SlidingWindowChunker(), embedder, store)
        assert await ingestor.ingest(RawRecord("a", "t", "abs"), "   ") == 0
        assert embedder.calls == []


class TestAsyncSimilarArticleFinder:
    @pytest.mark.asyncio
    async def test_find_similar_chunks_excludes_source(self):
        store = InMemoryEmbeddingStore()
        await store.add(_chunks(("a", 0, "self", [1.0, 0.0]), ("b", 0, "other", [0.95, 0.05])))
        finder = AsyncSimilarArticleFinder(_FakeEmbedder({"q": [1.0, 0.0]}), store)
        hits = await finder.find_similar_chunks("q", exclude_record_id="a")
        assert [hit.record_id for hit in hits] == ["b"]

    @pytest.mark.asyncio
    async def test_find_similar_articles_scores_by_best_chunk(self):
        store = InMemoryEmbeddingStore()
        await store.add(
            _chunks(
                ("b", 0, "weak", [0.3, 0.7]),
                ("b", 1, "strong", [0.99, 0.01]),
                ("c", 0, "mid", [0.7, 0.3]),
            )
        )
        finder = AsyncSimilarArticleFinder(_FakeEmbedder({"q": [1.0, 0.0]}), store)
        articles = await finder.find_similar_articles("q", top_k=2)
        assert [record_id for record_id, _, _ in articles] == ["b", "c"]
        assert articles[0][1] > 0.98


def _pipeline(mocker, *, relevant=True):
    extractor = mocker.Mock(spec=AsyncExtractor)
    extractor.search = mocker.AsyncMock(return_value=b"<feed/>")
    records = [RawRecord("1", "t", "a")]
    extractor.parse_listing = mocker.Mock(side_effect=[(records, 1), ([], 0)])
    extractor.fetch_full_text = mocker.AsyncMock(return_value="full body text")

    relevance = mocker.Mock(spec=AsyncRelevanceFilter)
    relevance.is_relevant = mocker.AsyncMock(return_value=relevant)

    entity = mocker.Mock(spec=AsyncEntityExtractor)
    entity.extract = mocker.AsyncMock(return_value=[{"name": "X"}])

    exporter = mocker.Mock(spec=AsyncExporter)
    exporter.export = mocker.AsyncMock()

    state = mocker.Mock(spec=AsyncStateManager)
    state.load_processed_ids = mocker.AsyncMock(return_value=set())
    state.load_metadata = mocker.AsyncMock(return_value=PipelineMetadata(last_start_index=0))
    state.mark_processed = mocker.AsyncMock()
    state.save_metadata = mocker.AsyncMock()

    ingestor = mocker.Mock()
    ingestor.ingest = mocker.AsyncMock(return_value=2)

    pipeline = AsyncETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entity,
        exporter=exporter,
        state_manager=state,
        destination="out.csv",
        sleep=mocker.AsyncMock(),
        memory_ingestor=ingestor,
    )
    return pipeline, extractor, ingestor


class TestPipelineTwoStageIngestion:
    @pytest.mark.asyncio
    async def test_ingests_full_text_after_relevance_pass(self, mocker):
        pipeline, _, ingestor = _pipeline(mocker, relevant=True)
        await pipeline.run(query="q", max_records=1, sleep_between=0)
        ingestor.ingest.assert_awaited_once()
        record, text = ingestor.ingest.await_args.args
        assert record.record_id == "1"
        assert text == "full body text"

    @pytest.mark.asyncio
    async def test_does_not_ingest_when_irrelevant(self, mocker):
        pipeline, extractor, ingestor = _pipeline(mocker, relevant=False)
        await pipeline.run(query="q", max_records=1, sleep_between=0)
        extractor.fetch_full_text.assert_not_called()
        ingestor.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_failure_is_logged_not_fatal(self, mocker):
        pipeline, _, ingestor = _pipeline(mocker, relevant=True)
        ingestor.ingest = mocker.AsyncMock(side_effect=EmbeddingStoreError("db locked"))
        logged: list[str] = []
        pipeline._log = logged.append
        assert await pipeline.run(query="q", max_records=1, sleep_between=0) == 1
        assert any("memory ingest failed" in message.lower() for message in logged)
