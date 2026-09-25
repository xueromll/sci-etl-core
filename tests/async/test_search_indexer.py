from __future__ import annotations

import asyncio

import pytest

from sci_etl_core.embeddings.chunking import SlidingWindowChunker
from sci_etl_core.embeddings.ingest_async import AsyncChunkIngestor
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.exceptions import EmbeddingError, EmbeddingStoreError, SearchQueryError, SearchStoreError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.ingest_async import AsyncCompositeIngestor
from sci_etl_core.ingest_protocol import MEMORY_FAULTS
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.search.index_async import AsyncSearchIndexer
from sci_etl_core.search.query import Term
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_memory import InMemoryTextSearchStore
from sci_etl_core.state.async_base import AsyncStateManager

RECORD = RawRecord("r1", "Dwarf galaxies", "An abstract", "https://arxiv.org/abs/r1", {"categories": ["GA"]})


class _Recording:
    def __init__(self, count: int = 2, delay: float = 0.0) -> None:
        self.count = count
        self.delay = delay
        self.finished = False

    async def ingest(self, record: RawRecord, text: str) -> int:
        await asyncio.sleep(self.delay)
        self.finished = True
        return self.count


class _Failing:
    def __init__(self, error: BaseException, delay: float = 0.0) -> None:
        self.error = error
        self.delay = delay

    async def ingest(self, record: RawRecord, text: str) -> int:
        await asyncio.sleep(self.delay)
        raise self.error


class _UnitEmbedder:
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class TestAsyncSearchIndexer:
    @pytest.mark.asyncio
    async def test_stores_the_title_abstract_text_and_a_copy_of_the_metadata(self):
        store = InMemoryTextSearchStore(facet_keys=("categories",))
        record = RawRecord("r1", "Dwarf galaxies", "An abstract", metadata={"categories": ["GA"], "year": "2024"})
        assert await AsyncSearchIndexer(store=store).ingest(record, "Full body") == 1
        record.metadata["year"] = "1999"
        metadata = {"categories": ["GA"], "year": "2024"}
        stored = SearchDocument("r1", "Dwarf galaxies", "An abstract", "Full body", metadata)
        assert await store.get_documents(["r1"]) == {"r1": stored}

    @pytest.mark.asyncio
    async def test_blank_fields_are_stored_as_empty_strings(self):
        store = InMemoryTextSearchStore()
        assert await AsyncSearchIndexer(store).ingest(RawRecord("r1", "Title", "   "), "\n\t") == 1
        assert await store.get_documents(["r1"]) == {"r1": SearchDocument("r1", "Title")}

    @pytest.mark.asyncio
    async def test_an_all_blank_record_is_cleared_from_the_index(self):
        store = InMemoryTextSearchStore()
        indexer = AsyncSearchIndexer(store)
        await indexer.ingest(RECORD, "body")
        assert await store.count() == 1
        assert await indexer.ingest(RawRecord("r1", " ", ""), "\t\n") == 0
        assert await store.count() == 0

    @pytest.mark.asyncio
    async def test_ingesting_again_replaces_rather_than_appends(self):
        store = InMemoryTextSearchStore()
        indexer = AsyncSearchIndexer(store)
        await indexer.ingest(RECORD, "quasar")
        await indexer.ingest(RECORD, "blazar")
        assert await store.filter_ids(Term("quasar")) == frozenset()
        assert await store.filter_ids(Term("blazar")) == frozenset({"r1"})

    @pytest.mark.asyncio
    async def test_a_store_fault_is_raised_not_swallowed(self, mocker):
        store = mocker.Mock(spec=InMemoryTextSearchStore)
        store.replace_record = mocker.AsyncMock(side_effect=SearchStoreError("disk full"))
        with pytest.raises(SearchStoreError, match="disk full"):
            await AsyncSearchIndexer(store).ingest(RECORD, "body")


class TestAsyncCompositeIngestor:
    def test_needs_at_least_one_ingestor(self):
        with pytest.raises(ValueError, match="needs at least one ingestor"):
            AsyncCompositeIngestor()

    def test_a_search_indexer_cannot_come_first_but_may_follow(self):
        indexer = AsyncSearchIndexer(InMemoryTextSearchStore())
        with pytest.raises(ValueError, match="must not be an AsyncSearchIndexer; pass the chunk ingestor first"):
            AsyncCompositeIngestor(indexer, _Recording())
        AsyncCompositeIngestor(_Recording(), indexer)

    def test_a_query_error_is_not_a_memory_fault(self):
        assert not any(issubclass(SearchQueryError, fault) for fault in MEMORY_FAULTS)

    @pytest.mark.asyncio
    async def test_returns_the_first_ingestors_count_once_every_ingestor_finished(self):
        slower = _Recording(count=1, delay=0.01)
        assert await AsyncCompositeIngestor(_Recording(count=3), slower).ingest(RECORD, "text") == 3
        assert slower.finished

    @pytest.mark.parametrize("error", [EmbeddingError("x"), EmbeddingStoreError("x"), SearchStoreError("x")])
    @pytest.mark.asyncio
    async def test_a_memory_fault_is_logged_and_the_other_ingestors_still_finish(self, error):
        logged: list[str] = []
        sibling = _Recording(delay=0.01)
        composite = AsyncCompositeIngestor(sibling, _Failing(error), logger=logged.append)
        assert await composite.ingest(RECORD, "text") == 2
        assert sibling.finished
        assert logged == [f"Memory ingest failed for r1 in _Failing: {error!r}"]

    @pytest.mark.asyncio
    async def test_an_absorbed_fault_in_the_first_ingestor_returns_zero(self):
        sibling = _Recording()
        assert await AsyncCompositeIngestor(_Failing(SearchStoreError("x")), sibling).ingest(RECORD, "text") == 0
        assert sibling.finished

    @pytest.mark.asyncio
    async def test_a_query_error_is_re_raised_after_the_other_ingestors_finish(self):
        logged: list[str] = []
        slow = _Recording(delay=0.05)
        composite = AsyncCompositeIngestor(slow, _Failing(SearchQueryError("bad")), logger=logged.append)
        with pytest.raises(SearchQueryError, match="bad"):
            await composite.ingest(RECORD, "text")
        assert slow.finished
        assert logged == []

    @pytest.mark.asyncio
    async def test_several_failures_re_raise_the_first_in_ingestor_order(self):
        slow_first = _Failing(RuntimeError("first"), delay=0.02)
        composite = AsyncCompositeIngestor(slow_first, _Failing(RuntimeError("second")))
        with pytest.raises(RuntimeError, match=r"^first$"):
            await composite.ingest(RECORD, "text")

    @pytest.mark.asyncio
    async def test_cancelling_the_caller_cancels_every_ingestor(self):
        started: list[str] = []
        cancelled: list[str] = []
        both_started = asyncio.Event()

        class Blocking:
            def __init__(self, name: str) -> None:
                self.name = name

            async def ingest(self, record: RawRecord, text: str) -> int:
                started.append(self.name)
                if len(started) == 2:
                    both_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.append(self.name)
                    raise
                return 0

        task = asyncio.create_task(AsyncCompositeIngestor(Blocking("a"), Blocking("b")).ingest(RECORD, "text"))
        await asyncio.wait_for(both_started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sorted(cancelled) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_an_ingestor_cancelled_on_its_own_is_re_raised_not_logged(self):
        logged: list[str] = []
        composite = AsyncCompositeIngestor(_Recording(), _Failing(asyncio.CancelledError()), logger=logged.append)
        with pytest.raises(asyncio.CancelledError):
            await composite.ingest(RECORD, "text")
        assert logged == []


LISTING = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-02T18:00:00Z</published>
    <title>Dwarf galaxies</title>
    <summary>Photometry of dwarf galaxies.</summary>
    <category term="astro-ph.GA"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2501.00002v1</id>
    <published>2025-03-04T18:00:00Z</published>
    <title>Cosmic web</title>
    <summary>Filaments between galaxies.</summary>
    <category term="astro-ph.CO"/>
    <category term="astro-ph.GA"/>
  </entry>
</feed>"""
EMPTY_LISTING = b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>"


def _arxiv_pipeline(mocker, ingestor, logged):
    responses = [mocker.Mock(status_code=200, content=content) for content in (LISTING, EMPTY_LISTING)]
    client = mocker.Mock()
    client.get = mocker.AsyncMock(side_effect=responses)
    extractor = AsyncArxivExtractor(
        client, pdf_parser=mocker.Mock(), latex_parser=mocker.Mock(), sleep=mocker.AsyncMock()
    )
    mocker.patch.object(extractor, "fetch_full_text", mocker.AsyncMock(side_effect=lambda r: f"full text of {r.title}"))

    relevance = mocker.Mock(spec=AsyncRelevanceFilter)
    relevance.is_relevant = mocker.AsyncMock(return_value=True)
    entity = mocker.Mock(spec=AsyncEntityExtractor)
    entity.extract = mocker.AsyncMock(return_value=[{"name": "X"}])
    exporter = mocker.Mock(spec=AsyncExporter)
    exporter.export = mocker.AsyncMock()
    state = mocker.Mock(spec=AsyncStateManager)
    state.load_processed_ids = mocker.AsyncMock(return_value=set())
    state.load_metadata = mocker.AsyncMock(return_value=PipelineMetadata())
    state.mark_processed = mocker.AsyncMock()
    state.save_metadata = mocker.AsyncMock()

    pipeline = AsyncETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entity,
        exporter=exporter,
        state_manager=state,
        destination="out.csv",
        logger=logged.append,
        sleep=mocker.AsyncMock(),
        memory_ingestor=ingestor,
    )
    return pipeline, exporter


class TestPipelineFanOut:
    @pytest.mark.asyncio
    async def test_arxiv_records_reach_both_memories_with_their_listing_metadata(self, mocker):
        logged: list[str] = []
        vectors = InMemoryEmbeddingStore()
        text_store = InMemoryTextSearchStore(facet_keys=("categories", "year"))
        ingestor = AsyncCompositeIngestor(
            AsyncChunkIngestor(chunker=SlidingWindowChunker(chunk_words=50), embedder=_UnitEmbedder(), store=vectors),
            AsyncSearchIndexer(store=text_store),
            logger=logged.append,
        )
        pipeline, exporter = _arxiv_pipeline(mocker, ingestor, logged)
        assert await pipeline.run(query="cat:astro-ph.GA", page_size=10, total_limit=10, sleep_between=0) == 2
        assert exporter.export.await_count == 2
        assert await vectors.count() == 2
        assert await text_store.count() == 2
        assert await text_store.facet_counts(["categories", "year"]) == {
            "categories": (("astro-ph.GA", 2), ("astro-ph.CO", 1)),
            "year": (("2024", 1), ("2025", 1)),
        }
        hits = await text_store.search(Term("filaments"))
        assert [(hit.record_id, hit.title) for hit in hits] == [("2501.00002v1", "Cosmic web")]
        assert logged == []

    @pytest.mark.asyncio
    async def test_a_broken_text_index_costs_neither_the_embeddings_nor_the_export(self, mocker):
        logged: list[str] = []
        vectors = InMemoryEmbeddingStore()
        broken = mocker.Mock(spec=InMemoryTextSearchStore)
        broken.replace_record = mocker.AsyncMock(side_effect=SearchStoreError("database is locked"))
        ingestor = AsyncCompositeIngestor(
            AsyncChunkIngestor(chunker=SlidingWindowChunker(chunk_words=50), embedder=_UnitEmbedder(), store=vectors),
            AsyncSearchIndexer(store=broken),
            logger=logged.append,
        )
        pipeline, exporter = _arxiv_pipeline(mocker, ingestor, logged)
        assert await pipeline.run(query="cat:astro-ph.GA", page_size=10, total_limit=10, sleep_between=0) == 2
        assert exporter.export.await_count == 2
        assert await vectors.count() == 2
        assert sorted(logged) == [
            "Memory ingest failed for 2401.00001v1 in AsyncSearchIndexer: SearchStoreError('database is locked')",
            "Memory ingest failed for 2501.00002v1 in AsyncSearchIndexer: SearchStoreError('database is locked')",
        ]
