from __future__ import annotations

import asyncio

import pytest

from sci_etl_core.embeddings.finder_async import AsyncSimilarArticleFinder
from sci_etl_core.embeddings.store_base import EmbeddingChunk
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.exceptions import EmbeddingError, SearchQueryError, SearchStoreError
from sci_etl_core.search.filters import MetadataFilter, RangeFilter
from sci_etl_core.search.fusion import FusionParams, normalized_score_fusion
from sci_etl_core.search.hybrid_async import AsyncHybridSearcher, HybridParams, SearchOutcome
from sci_etl_core.search.store_base import SearchDocument, Snippet
from sci_etl_core.search.store_memory import InMemoryTextSearchStore

NOT_RANKABLE = "A ranked search needs at least one term that is not negated"
DOCUMENTS = [
    SearchDocument("dwarf", title="Dwarf galaxies", abstract="Photometry of dwarf galaxies", metadata={"year": "2024"}),
    SearchDocument("streams", title="Stellar streams", abstract="Tidal debris", metadata={"year": "2025"}),
    SearchDocument("quasar", title="Quasar hosts", abstract="Dwarf companions of quasars", metadata={"year": "2025"}),
]
CHUNKS = [
    EmbeddingChunk("dwarf", 0, "chunk", [1.0, 0.0], {"title": "Dwarf galaxies"}),
    EmbeddingChunk("streams", 0, "chunk", [0.8, 0.6], {"title": "Stellar streams"}),
    EmbeddingChunk("quasar", 0, "chunk", [0.0, 1.0], {"title": "Quasar hosts"}),
]


class TableEmbedder:
    def __init__(self, error: BaseException | None = None, delay: float = 0.0) -> None:
        self.error = error
        self.delay = delay
        self.calls: list[list[str]] = []
        self.finished = False

    async def embed(self, texts):
        self.calls.append(list(texts))
        await asyncio.sleep(self.delay)
        self.finished = True
        if self.error is not None:
            raise self.error
        return [[1.0, 0.0] for _ in texts]


async def build(text_store=None, embedder=None, chunks=CHUNKS, with_finder=True, **options):
    text_store = InMemoryTextSearchStore(facet_keys=("year",)) if text_store is None else text_store
    await text_store.index(DOCUMENTS)
    vectors = InMemoryEmbeddingStore()
    await vectors.add(chunks)
    embedder = TableEmbedder() if embedder is None else embedder
    finder = AsyncSimilarArticleFinder(embedder, vectors) if with_finder else None
    return AsyncHybridSearcher(text_store, finder, **options), text_store, embedder


def ranks(outcome):
    return [(hit.record_id, hit.lexical_rank, hit.semantic_rank) for hit in outcome.hits]


class TestModes:
    @pytest.mark.asyncio
    async def test_hybrid_search_fuses_both_legs(self):
        searcher, _, _ = await build()
        outcome = await searcher.search("dwarf galaxies")
        assert ranks(outcome) == [("dwarf", 1, 1), ("streams", None, 2), ("quasar", None, 3)]
        assert outcome.hits[0].score == pytest.approx(2 / 61)
        assert (outcome.degraded, outcome.skipped) == ((), ())
        lexical = outcome.hits[0]
        assert lexical.title == "Dwarf galaxies"
        assert [lexical.snippet[start:end] for start, end in lexical.highlights] == ["Dwarf", "galaxies"]
        assert [snippet.field for snippet in lexical.snippets] == ["title", "abstract"]
        semantic_only = outcome.hits[1]
        assert (semantic_only.snippet, semantic_only.highlights) == ("chunk", ())
        assert semantic_only.snippets == (Snippet("body", "chunk"),)
        assert (semantic_only.title, semantic_only.metadata) == ("Stellar streams", {"year": "2025"})

    @pytest.mark.asyncio
    async def test_lexical_mode_never_embeds(self):
        searcher, _, embedder = await build()
        outcome = await searcher.search("dwarf galaxies", mode="lexical")
        assert ranks(outcome) == [("dwarf", 1, None)]
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_semantic_mode_never_searches_the_text_index(self, mocker):
        searcher, text_store, _ = await build()
        search = mocker.spy(text_store, "search")
        outcome = await searcher.search("dwarf galaxies", mode="semantic")
        assert ranks(outcome) == [("dwarf", None, 1), ("streams", None, 2), ("quasar", None, 3)]
        assert outcome.hits[0].title == "Dwarf galaxies"
        search.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_two_legs_run_concurrently(self):
        lexical_started, semantic_started = asyncio.Event(), asyncio.Event()

        class GatedStore(InMemoryTextSearchStore):
            async def search(self, *args, **kwargs):
                lexical_started.set()
                await asyncio.wait_for(semantic_started.wait(), 2)
                return await super().search(*args, **kwargs)

        class GatedEmbedder(TableEmbedder):
            async def embed(self, texts):
                semantic_started.set()
                await asyncio.wait_for(lexical_started.wait(), 2)
                return await super().embed(texts)

        searcher, _, _ = await build(text_store=GatedStore(), embedder=GatedEmbedder())
        assert len((await searcher.search("dwarf galaxies")).hits) == 3

    @pytest.mark.asyncio
    async def test_an_unknown_mode_is_rejected(self):
        searcher, _, embedder = await build()
        with pytest.raises(ValueError, match="Unknown search mode 'fuzzy'"):
            await searcher.search("dwarf", mode="fuzzy")
        assert embedder.calls == []


class TestQueryHandling:
    @pytest.mark.parametrize("mode", ["lexical", "semantic", "hybrid"])
    @pytest.mark.asyncio
    async def test_a_pure_negation_is_refused_in_every_mode_before_any_io(self, mocker, mode):
        searcher, text_store, embedder = await build()
        search = mocker.spy(text_store, "search")
        with pytest.raises(SearchQueryError, match=NOT_RANKABLE) as raised:
            await searcher.search("NOT dwarf OR quasar", mode=mode)
        assert (raised.value.position, raised.value.token) == (0, "NOT")
        search.assert_not_called()
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_a_prefix_only_hybrid_query_skips_the_semantic_leg(self):
        searcher, _, embedder = await build()
        outcome = await searcher.search("photometr*")
        assert ranks(outcome) == [("dwarf", 1, None)]
        assert (outcome.degraded, outcome.skipped) == ((), ("semantic",))
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_a_prefix_only_semantic_query_is_a_located_query_error(self):
        searcher, _, embedder = await build()
        with pytest.raises(SearchQueryError, match="needs at least one whole word") as raised:
            await searcher.search("-quasar title:photometr*", mode="semantic")
        assert (raised.value.position, raised.value.token) == (8, "title:photometr*")
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_the_embedder_sees_the_meaning_and_or_reads_as_and(self):
        searcher, _, embedder = await build()
        await searcher.search("dwarf OR galaxies", mode="semantic")
        await searcher.search("title:dwarf galaxies -quasar photometr*", mode="semantic")
        assert embedder.calls == [["dwarf galaxies"], ["dwarf galaxies"]]


class TestWithoutAFinder:
    @pytest.mark.asyncio
    async def test_semantic_mode_is_a_request_error_without_a_position(self):
        searcher, _, _ = await build(with_finder=False)
        with pytest.raises(SearchQueryError, match="Semantic mode requires a finder") as raised:
            await searcher.search("dwarf galaxies", mode="semantic")
        assert (raised.value.position, raised.value.token) == (None, "")

    @pytest.mark.asyncio
    async def test_hybrid_mode_returns_lexical_hits_and_reports_the_semantic_leg_skipped(self):
        searcher, _, _ = await build(with_finder=False)
        outcome = await searcher.search("dwarf galaxies")
        assert ranks(outcome) == [("dwarf", 1, None)]
        assert (outcome.degraded, outcome.skipped) == ((), ("semantic",))


class TestFailures:
    @pytest.mark.asyncio
    async def test_an_embedding_failure_degrades_a_hybrid_search_to_lexical(self):
        logged: list[str] = []
        searcher, _, _ = await build(embedder=TableEmbedder(EmbeddingError("unreachable")), logger=logged.append)
        outcome = await searcher.search("dwarf galaxies")
        assert ranks(outcome) == [("dwarf", 1, None)]
        assert (outcome.degraded, outcome.skipped) == (("semantic",), ())
        assert logged == ["Semantic search failed; showing lexical results only: EmbeddingError('unreachable')"]

    @pytest.mark.asyncio
    async def test_the_default_logger_is_silent(self):
        searcher, _, _ = await build(embedder=TableEmbedder(EmbeddingError("unreachable")))
        assert (await searcher.search("dwarf galaxies")).degraded == ("semantic",)

    @pytest.mark.asyncio
    async def test_an_embedding_failure_fails_a_semantic_search(self):
        searcher, _, _ = await build(embedder=TableEmbedder(EmbeddingError("unreachable")))
        with pytest.raises(EmbeddingError, match="unreachable"):
            await searcher.search("dwarf galaxies", mode="semantic")

    @pytest.mark.asyncio
    async def test_a_cancelled_semantic_leg_is_re_raised(self):
        searcher, _, _ = await build(embedder=TableEmbedder(asyncio.CancelledError()))
        with pytest.raises(asyncio.CancelledError):
            await searcher.search("dwarf galaxies")

    @pytest.mark.asyncio
    async def test_a_lexical_failure_is_raised_once_the_semantic_leg_finished(self):
        class BrokenStore(InMemoryTextSearchStore):
            async def search(self, *args, **kwargs):
                raise SearchStoreError("database disk image is malformed")

        embedder = TableEmbedder(delay=0.02)
        searcher, _, _ = await build(text_store=BrokenStore(), embedder=embedder)
        with pytest.raises(SearchStoreError, match="malformed"):
            await searcher.search("dwarf galaxies")
        assert embedder.finished

    @pytest.mark.asyncio
    async def test_a_failure_to_read_the_filter_set_is_raised(self):
        class BrokenFilters(InMemoryTextSearchStore):
            async def filter_ids(self, *args, **kwargs):
                raise SearchStoreError("tags are not built")

        searcher, _, _ = await build(text_store=BrokenFilters(facet_keys=("year",)))
        with pytest.raises(SearchStoreError, match="tags are not built"):
            await searcher.search("dwarf galaxies", filters=[MetadataFilter("year", {"2025"})])


class TestFiltersAndLimits:
    @pytest.mark.asyncio
    async def test_filters_narrow_both_legs_before_fusion(self):
        searcher, _, _ = await build()
        outcome = await searcher.search("dwarf galaxies", filters=[MetadataFilter("year", {"2025"})])
        assert ranks(outcome) == [("streams", None, 1), ("quasar", None, 2)]

    @pytest.mark.asyncio
    async def test_range_filters_narrow_both_legs_before_fusion(self):
        searcher, _, _ = await build()
        outcome = await searcher.search("dwarf galaxies", filters=[RangeFilter("year", low="2025")])
        assert ranks(outcome) == [("streams", None, 1), ("quasar", None, 2)]

    @pytest.mark.asyncio
    async def test_invalid_filters_raise_before_any_io(self, mocker):
        searcher, text_store, embedder = await build()
        search = mocker.spy(text_store, "search")
        twice = [MetadataFilter("year", {"2024"}), MetadataFilter("year", {"2025"}, negated=True)]
        with pytest.raises(ValueError, match="Only one filter per key"):
            await searcher.search("dwarf", filters=twice)
        with pytest.raises(ValueError, match="'authors' is not a facet key"):
            await searcher.search("dwarf", filters=[MetadataFilter("authors", {"A"})])
        search.assert_not_called()
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_top_k_cuts_the_fused_list_and_below_one_returns_nothing(self):
        searcher, _, embedder = await build()
        assert ranks(await searcher.search("dwarf galaxies", top_k=1)) == [("dwarf", 1, 1)]
        assert await searcher.search("dwarf galaxies", top_k=0) == SearchOutcome()
        assert await searcher.search("photometr*", top_k=0) == SearchOutcome(skipped=("semantic",))
        assert embedder.calls == [["dwarf galaxies"]]

    @pytest.mark.asyncio
    async def test_a_semantic_hit_missing_from_the_text_index_keeps_its_chunk_metadata(self):
        chunks = [*CHUNKS, EmbeddingChunk("vectors-only", 0, "chunk", [0.9, 0.1], {"title": 7})]
        searcher, text_store, _ = await build(chunks=chunks)
        await text_store.delete_record("streams")
        outcome = await searcher.search("dwarf galaxies", mode="semantic")
        by_id = {hit.record_id: hit for hit in outcome.hits}
        assert (by_id["streams"].title, by_id["streams"].metadata) == ("Stellar streams", {"title": "Stellar streams"})
        assert (by_id["vectors-only"].title, by_id["vectors-only"].metadata) == ("", {"title": 7})


class TestSemanticSnippets:
    @pytest.mark.asyncio
    async def test_a_semantic_only_hit_shows_its_best_passage_with_the_query_words_highlighted(self):
        long_passage = " ".join([*(f"w{index}" for index in range(30)), "dwarf", "satellites"])
        chunks = [
            *CHUNKS[:2],
            EmbeddingChunk("quasar", 0, "Quasar hosts with dwarf companions", [0.0, 1.0], {"title": "Quasar hosts"}),
            EmbeddingChunk("vectors-only", 0, long_passage, [0.9, 0.1], {"title": "Satellites"}),
        ]
        searcher, _, _ = await build(chunks=chunks)
        outcome = await searcher.search("dwarf -galaxies", mode="semantic")
        by_id = {hit.record_id: hit for hit in outcome.hits}
        quasar = by_id["quasar"]
        assert quasar.snippet == "Quasar hosts with dwarf companions"
        assert [quasar.snippet[start:end] for start, end in quasar.highlights] == ["dwarf"]
        assert quasar.snippets == (Snippet("body", quasar.snippet, quasar.highlights),)
        satellites = by_id["vectors-only"]
        assert satellites.snippet.startswith("…")
        assert satellites.snippet.endswith("dwarf satellites")
        assert [satellites.snippet[start:end] for start, end in satellites.highlights] == ["dwarf"]

    @pytest.mark.asyncio
    async def test_a_hit_both_legs_found_keeps_the_lexical_snippets(self):
        searcher, _, _ = await build()
        outcome = await searcher.search("photometry")
        (hit, *_) = outcome.hits
        assert (hit.record_id, hit.lexical_rank, hit.semantic_rank) == ("dwarf", 1, 1)
        assert hit.snippets == (Snippet("abstract", "Photometry of dwarf galaxies", ((0, 10),)),)


class TestFusionConfiguration:
    @pytest.mark.asyncio
    async def test_fusion_weights_are_the_lexical_then_the_semantic_weight(self):
        searcher, _, _ = await build(fusion=FusionParams(weights=(1.0, 0.0)))
        outcome = await searcher.search("dwarf galaxies")
        assert ranks(outcome) == [("dwarf", 1, 1), ("quasar", None, 3), ("streams", None, 2)]
        assert [hit.score for hit in outcome.hits[1:]] == [0.0, 0.0]
        semantic_only = await searcher.search("dwarf galaxies", mode="semantic")
        assert [hit.record_id for hit in semantic_only.hits] == ["dwarf", "quasar", "streams"]

    @pytest.mark.parametrize("weights", [(1.0,), (1.0, 1.0, 1.0)])
    def test_the_fusion_weights_must_be_two(self, weights):
        with pytest.raises(ValueError, match="must hold two weights"):
            AsyncHybridSearcher(InMemoryTextSearchStore(), fusion=FusionParams(weights=weights))

    @pytest.mark.asyncio
    async def test_another_fusion_strategy_can_be_used(self):
        searcher, _, _ = await build(strategy=normalized_score_fusion)
        outcome = await searcher.search("dwarf galaxies")
        assert [(hit.record_id, hit.score) for hit in outcome.hits] == [
            ("dwarf", 2.0),
            ("streams", pytest.approx(0.8)),
            ("quasar", 0.0),
        ]


def _article_chunks(record_ids, chunks_per_record, vector):
    return [
        EmbeddingChunk(record_id, index, "chunk", vector(record_id, index), {"title": record_id})
        for record_id in record_ids
        for index in range(chunks_per_record)
    ]


class TestCandidatePool:
    @pytest.mark.asyncio
    async def test_the_pool_fills_when_no_record_has_more_chunks_than_the_factor(self, mocker):
        records = [f"r{index:02d}" for index in range(15)]
        chunks = _article_chunks(records, 3, lambda record_id, index: [1.0, int(record_id[1:]) * 0.1 + index * 0.01])
        searcher, _, _ = await build(chunks=chunks, params=HybridParams(candidate_pool=10, chunk_pool_factor=3))
        find = mocker.spy(AsyncSimilarArticleFinder, "find_best_chunks")
        outcome = await searcher.search("galaxies", top_k=10, mode="semantic")
        assert len(outcome.hits) >= min(10, len(records))
        assert find.call_args.kwargs == {"top_k": 10, "chunk_pool": 30}

    @pytest.mark.asyncio
    async def test_records_that_own_every_top_chunk_leave_the_pool_short_without_a_retry(self):
        dominant = _article_chunks(["a", "b"], 30, lambda record_id, index: [1.0, 0.0])
        others = _article_chunks([f"o{index}" for index in range(10)], 1, lambda record_id, index: [0.5, 0.5])
        embedder = TableEmbedder()
        searcher, _, _ = await build(
            chunks=[*dominant, *others], embedder=embedder, params=HybridParams(candidate_pool=10, chunk_pool_factor=2)
        )
        outcome = await searcher.search("galaxies", top_k=10, mode="semantic")
        assert sorted(hit.record_id for hit in outcome.hits) == ["a", "b"]
        assert len(embedder.calls) == 1

    @pytest.mark.asyncio
    async def test_the_pool_is_never_smaller_than_top_k(self):
        searcher, _, _ = await build(params=HybridParams(candidate_pool=1, chunk_pool_factor=1))
        assert len((await searcher.search("dwarf galaxies", top_k=3, mode="semantic")).hits) == 3

    @pytest.mark.parametrize("options", [{"candidate_pool": 0}, {"chunk_pool_factor": 0}])
    def test_pool_parameters_below_one_are_rejected(self, options):
        with pytest.raises(ValueError, match="must be at least 1"):
            HybridParams(**options)
