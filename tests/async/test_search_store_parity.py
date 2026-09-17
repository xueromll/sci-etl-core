from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from sci_etl_core.exceptions import SearchQueryError
from sci_etl_core.search.filters import MetadataFilter, RangeFilter
from sci_etl_core.search.parser import parse_query
from sci_etl_core.search.query import Not, Term
from sci_etl_core.search.store_base import BM25Weights, SearchDocument, Snippet
from sci_etl_core.search.store_memory import InMemoryTextSearchStore
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store
from sci_etl_core.search.tokenize import Unicode61Tokenizer

BACKENDS = ["memory", "fts5"]
NOT_RANKABLE = "A ranked search needs at least one term that is not negated"
ARTICLE = "H-alpha photometry of nearby dwarf galaxies"
PUBLISHED = datetime(2026, 9, 15, 8, 20, tzinfo=timezone.utc)
FACETS = ("categories", "year")
FACET_DOCUMENTS = [
    SearchDocument("d1", title="galaxy", metadata={"categories": ["GA", "CO"], "year": "2025"}),
    SearchDocument("d2", title="galaxy", metadata={"categories": ["CO"], "year": "2025"}),
    SearchDocument("d3", title="galaxy", metadata={"categories": ["HE"], "year": "2025"}),
    SearchDocument("d4", title="galaxy", metadata={"categories": ["GA"], "year": "2024"}),
]
SELECTED = [MetadataFilter("categories", {"GA"}), MetadataFilter("year", {"2025"})]
IN_BODY_AND_IN_TITLE = [
    SearchDocument("in-body", title="survey", body="galaxy"),
    SearchDocument("in-title", title="galaxy", body="survey"),
]
DATED_DOCUMENTS = [
    SearchDocument(
        f"y{year}",
        title="galaxy",
        metadata={
            "year": year,
            "published": f"{year}-06-30T10:00:00Z",
            "categories": ["GA"] if year % 2 else ["CO"],
        },
    )
    for year in range(2018, 2026)
]
DATED_FACETS = ("year", "published", "categories")
DWARF_AND_GIANT = [
    SearchDocument("a", title="dwarf"),
    SearchDocument("b", title="giant"),
    SearchDocument("c", title="dwarf giant"),
]


@asynccontextmanager
async def open_store(kind, directory, **options):
    if kind == "memory":
        store = InMemoryTextSearchStore(**options)
    else:
        store = AsyncSqliteFts5Store(directory / f"{kind}.db", **options)
    try:
        yield store
    finally:
        await store.aclose()


def marked(hit):
    return [hit.snippet[start:end] for start, end in hit.highlights]


@pytest.mark.parametrize("kind", BACKENDS)
class TestTextSearchStoreContract:
    @pytest.mark.asyncio
    async def test_documents_are_counted_and_read_back_with_json_metadata(self, kind, tmp_path):
        stored = {"published": PUBLISHED, "authors": ["Müller"]}
        read_back = {"published": "2026-09-15T08:20:00+00:00", "authors": ["Müller"]}
        async with open_store(kind, tmp_path) as store:
            await store.index([])
            assert await store.count() == 0
            await store.index(
                [
                    SearchDocument("r1", "Dwarf galaxies", "An abstract", "Body", stored),
                    SearchDocument("r2", title="Quasars"),
                ]
            )
            assert await store.count() == 2
            assert await store.get_documents(["r1", "r2", "unknown"]) == {
                "r1": SearchDocument("r1", "Dwarf galaxies", "An abstract", "Body", read_back),
                "r2": SearchDocument("r2", title="Quasars"),
            }
            assert await store.get_documents([]) == {}

    @pytest.mark.asyncio
    async def test_indexing_a_record_again_replaces_it(self, kind, tmp_path):
        async with open_store(kind, tmp_path) as store:
            await store.index([SearchDocument("r1", title="quasar"), SearchDocument("r1", title="blazar")])
            assert await store.count() == 1
            assert await store.filter_ids(Term("quasar")) == frozenset()
            await store.replace_record(SearchDocument("r1", title="pulsar"))
            assert await store.filter_ids(Term("blazar")) == frozenset()
            assert [hit.record_id for hit in await store.search(Term("pulsar"))] == ["r1"]
            await store.delete_record("r1")
            await store.delete_record("never-indexed")
            assert await store.count() == 0

    @pytest.mark.asyncio
    async def test_hits_are_ranked_best_first_by_weighted_fields(self, kind, tmp_path):
        fillers = [SearchDocument(f"f{index}", title="unrelated", body="filler text") for index in range(5)]
        async with open_store(kind, tmp_path) as store:
            await store.index([*IN_BODY_AND_IN_TITLE, *fillers])
            hits = await store.search(Term("galaxy"))
            assert [hit.record_id for hit in hits] == ["in-title", "in-body"]
            assert hits[0].score > hits[1].score > 0
            assert (hits[0].title, hits[1].title) == ("galaxy", "survey")

    @pytest.mark.asyncio
    async def test_the_field_weights_are_configurable(self, kind, tmp_path):
        async with open_store(kind, tmp_path, weights=BM25Weights(title=0.0, abstract=0.0, body=1.0)) as store:
            await store.index(IN_BODY_AND_IN_TITLE)
            assert [hit.record_id for hit in await store.search(Term("galaxy"))] == ["in-body", "in-title"]

    @pytest.mark.asyncio
    async def test_a_near_query_ranks_only_records_whose_words_are_close(self, kind, tmp_path):
        documents = [
            SearchDocument("close", title="dwarf spheroidal galaxy"),
            SearchDocument("far", title="dwarf stars in a distant massive galaxy"),
            SearchDocument("other", title="giant elliptical"),
        ]
        async with open_store(kind, tmp_path) as store:
            await store.index(documents)
            hits = await store.search(parse_query('NEAR("dwarf galaxy", 2)'))
            assert [hit.record_id for hit in hits] == ["close"]
            assert hits[0].score > 0

    @pytest.mark.asyncio
    async def test_equal_scores_are_ordered_by_record_id_whatever_the_insertion_history(self, kind, tmp_path):
        forward_directory, backward_directory = tmp_path / "forward", tmp_path / "backward"
        forward_directory.mkdir()
        backward_directory.mkdir()
        fillers = [SearchDocument(f"f{index}", title="other") for index in range(4)]

        def identical(record_id):
            return SearchDocument(record_id, title="dwarf galaxy")

        async with open_store(kind, forward_directory) as forward, open_store(kind, backward_directory) as backward:
            await forward.index([identical("r1"), identical("r2"), identical("r3"), *fillers])
            await backward.index([*fillers, identical("r3"), identical("r2"), identical("r1")])
            await backward.delete_record("r3")
            await backward.index([identical("r3")])
            for store in (forward, backward):
                hits = await store.search(Term("galaxy"))
                assert [hit.record_id for hit in hits] == ["r1", "r2", "r3"]
                assert len({hit.score for hit in hits}) == 1
                assert [hit.record_id for hit in await store.search(Term("galaxy"), limit=2)] == ["r1", "r2"]

    @pytest.mark.asyncio
    async def test_limit_and_exclusion(self, kind, tmp_path):
        async with open_store(kind, tmp_path) as store:
            await store.index([SearchDocument(record_id, title="galaxy") for record_id in ("a", "b", "c")])
            assert await store.search(Term("galaxy"), limit=0) == []
            assert await store.search(Term("galaxy"), limit=-1) == []
            assert [hit.record_id for hit in await store.search(Term("galaxy"), exclude_record_id="b")] == ["a", "c"]
            assert await store.search(Term("galaxy"), exclude_record_id="a", limit=1) != []
            assert await store.search(Term("quasar")) == []

    @pytest.mark.asyncio
    async def test_a_pure_negation_is_refused_by_search_and_answered_by_filter_ids(self, kind, tmp_path):
        async with open_store(kind, tmp_path) as store:
            await store.index(DWARF_AND_GIANT)
            for query in (Not(Term("dwarf")), parse_query("NOT dwarf OR giant")):
                with pytest.raises(SearchQueryError, match=NOT_RANKABLE):
                    await store.search(query)
            assert await store.filter_ids(Not(Term("dwarf"))) == frozenset({"b"})
            assert await store.filter_ids(parse_query("NOT dwarf OR giant")) == frozenset({"b", "c"})
            assert await store.filter_ids() == frozenset({"a", "b", "c"})

    @pytest.mark.parametrize(
        "query, words",
        [
            ('"dwarf galaxies"', ["dwarf galaxies"]),
            ("photometr*", ["photometry"]),
            ("galaxies dwarf", ["dwarf", "galaxies"]),
            ("nearby -quasar", ["nearby"]),
            ("nearby OR (dwarf quasar)", ["nearby"]),
            ("photometr* OR (galaxies -nearby)", ["photometry"]),
        ],
    )
    @pytest.mark.asyncio
    async def test_highlights_are_offsets_of_the_matched_words(self, kind, tmp_path, query, words):
        async with open_store(kind, tmp_path) as store:
            await store.index([SearchDocument("r1", title="Survey", abstract=ARTICLE)])
            (hit,) = await store.search(parse_query(query))
            assert hit.snippet == ARTICLE
            assert marked(hit) == words

    @pytest.mark.asyncio
    async def test_overlapping_occurrences_are_highlighted_as_one_span(self, kind, tmp_path):
        async with open_store(kind, tmp_path) as store:
            await store.index([SearchDocument("r1", title="dwarf dwarf dwarf", abstract="survey")])
            (hit,) = await store.search(parse_query('"dwarf dwarf"'))
            assert marked(hit) == ["dwarf dwarf dwarf"]

    @pytest.mark.asyncio
    async def test_facet_keys_are_fixed_at_construction(self, kind, tmp_path):
        async with open_store(kind, tmp_path, facet_keys=["year", "categories", "year"]) as store:
            assert store.facet_keys == frozenset({"year", "categories"})

    @pytest.mark.asyncio
    async def test_a_long_field_is_cut_to_a_window_around_the_match(self, kind, tmp_path):
        words = [f"w{index}" for index in range(60)]
        words[40] = "galaxy"
        async with open_store(kind, tmp_path) as store:
            await store.index([SearchDocument("r1", body=" ".join(words))])
            (hit,) = await store.search(Term("galaxy"))
            assert "…" in hit.snippet
            assert marked(hit) == ["galaxy"]
            assert len(Unicode61Tokenizer().tokens(hit.snippet)) <= 24

    @pytest.mark.asyncio
    async def test_metadata_filters_apply_before_the_limit(self, kind, tmp_path):
        documents = [
            SearchDocument(f"r{index}", title="galaxy", body="galaxy " * index, metadata={"year": str(2020 + index)})
            for index in range(6)
        ]
        async with open_store(kind, tmp_path, facet_keys=("year",)) as store:
            await store.index(documents)
            recent = [MetadataFilter("year", {"2024", "2025"})]
            hits = await store.search(Term("galaxy"), limit=2, filters=recent)
            assert {hit.record_id for hit in hits} == {"r4", "r5"}
            older = [MetadataFilter("year", {"2024", "2025"}, negated=True)]
            assert len(await store.search(Term("galaxy"), limit=10, filters=older)) == 4
            assert await store.filter_ids(Term("galaxy"), recent) == frozenset({"r4", "r5"})

    @pytest.mark.asyncio
    async def test_facet_counts_ignore_each_keys_own_filter(self, kind, tmp_path):
        async with open_store(kind, tmp_path, facet_keys=FACETS) as store:
            await store.index(FACET_DOCUMENTS)
            assert await store.facet_counts(FACETS, query=Term("galaxy"), filters=SELECTED) == {
                "categories": (("CO", 2), ("GA", 1), ("HE", 1)),
                "year": (("2024", 1), ("2025", 1)),
            }
            every_filter = await store.get_documents(await store.filter_ids(Term("galaxy"), SELECTED))
            applied = Counter(value for document in every_filter.values() for value in document.metadata["categories"])
            assert sorted(applied.items()) == [("CO", 1), ("GA", 1)]

    @pytest.mark.asyncio
    async def test_a_key_without_a_filter_counts_over_the_whole_match_set(self, kind, tmp_path):
        async with open_store(kind, tmp_path, facet_keys=FACETS) as store:
            await store.index(FACET_DOCUMENTS)
            assert await store.facet_counts(["year"], query=Term("galaxy")) == {"year": (("2025", 3), ("2024", 1))}
            assert await store.facet_counts(["year"], filters=[MetadataFilter("categories", {"GA"})]) == {
                "year": (("2024", 1), ("2025", 1))
            }

    @pytest.mark.asyncio
    async def test_values_with_no_matching_document_are_omitted(self, kind, tmp_path):
        async with open_store(kind, tmp_path, facet_keys=FACETS) as store:
            await store.index(FACET_DOCUMENTS)
            assert await store.facet_counts(["categories"], filters=[MetadataFilter("year", {"2024"})]) == {
                "categories": (("GA", 1),)
            }
            assert await store.facet_counts(FACETS, query=Term("quasar")) == {"categories": (), "year": ()}

    @pytest.mark.asyncio
    async def test_invalid_requests_raise_before_any_io(self, kind, tmp_path):
        twice = [MetadataFilter("year", {"2024"}), MetadataFilter("year", {"2025"}, negated=True)]
        unknown = [MetadataFilter("authors", {"A"})]
        async with open_store(kind, tmp_path / "never-created", facet_keys=FACETS) as store:
            for filters, message in ((twice, "Only one filter per key"), (unknown, "'authors' is not a facet key")):
                with pytest.raises(ValueError, match=message):
                    await store.search(Term("galaxy"), filters=filters)
                with pytest.raises(ValueError, match=message):
                    await store.filter_ids(filters=filters)
                with pytest.raises(ValueError, match=message):
                    await store.facet_counts(["year"], filters=filters)
            with pytest.raises(ValueError, match="'authors' is not a facet key"):
                await store.facet_counts(["authors"])
            with pytest.raises(SearchQueryError):
                await store.search(Not(Term("galaxy")))

    @pytest.mark.asyncio
    async def test_repeated_and_unchanged_tag_values_never_collide(self, kind, tmp_path):
        async with open_store(kind, tmp_path, facet_keys=("authors", "year")) as store:
            document = SearchDocument("r1", title="galaxy", metadata={"authors": ["A", "B", "A"], "year": "2025"})
            await store.index([document])
            await store.index([document])
            assert await store.facet_counts(["authors", "year"]) == {
                "authors": (("A", 1), ("B", 1)),
                "year": (("2025", 1),),
            }
            await store.index([SearchDocument("r1", title="galaxy", metadata={"authors": ["B"], "year": 2024})])
            assert await store.facet_counts(["authors", "year"]) == {"authors": (("B", 1),), "year": (("2024", 1),)}

    @pytest.mark.parametrize(
        "filters, expected",
        [
            ([RangeFilter("year", 2020, 2022)], ["y2020", "y2021", "y2022"]),
            ([RangeFilter("year", "2024")], ["y2024", "y2025"]),
            ([RangeFilter("published", "2021", "2022-06")], ["y2021", "y2022"]),
            ([RangeFilter("published", high="2019-06-30T09")], ["y2018"]),
            (
                [RangeFilter("year", low=2024, negated=True), MetadataFilter("categories", {"GA"})],
                ["y2019", "y2021", "y2023"],
            ),
            ([RangeFilter("categories", low="H")], []),
        ],
    )
    @pytest.mark.asyncio
    async def test_range_filters_select_tags_between_their_bounds(self, kind, tmp_path, filters, expected):
        async with open_store(kind, tmp_path, facet_keys=DATED_FACETS) as store:
            await store.index(DATED_DOCUMENTS)
            assert sorted(await store.filter_ids(Term("galaxy"), filters)) == expected
            hits = await store.search(Term("galaxy"), limit=2, filters=filters)
            assert [hit.record_id for hit in hits] == expected[:2]

    @pytest.mark.asyncio
    async def test_facet_counts_apply_range_filters_on_other_keys(self, kind, tmp_path):
        async with open_store(kind, tmp_path, facet_keys=DATED_FACETS) as store:
            await store.index(DATED_DOCUMENTS)
            recent = [RangeFilter("year", low=2022), MetadataFilter("categories", {"GA"})]
            assert await store.facet_counts(["categories", "year"], filters=recent) == {
                "categories": (("CO", 2), ("GA", 2)),
                "year": (("2019", 1), ("2021", 1), ("2023", 1), ("2025", 1)),
            }

    @pytest.mark.asyncio
    async def test_range_counts_count_each_range_without_filters_on_its_own_key(self, kind, tmp_path):
        async with open_store(kind, tmp_path, facet_keys=DATED_FACETS) as store:
            await store.index(DATED_DOCUMENTS)
            buckets = [
                RangeFilter("year", 2018, 2019),
                RangeFilter("year", 2020, 2025),
                RangeFilter("year", 2020, 2025, negated=True),
                RangeFilter("published", high="2020-12"),
            ]
            filters = [RangeFilter("year", low=2025), MetadataFilter("categories", {"GA"})]
            assert await store.range_counts(buckets, query=Term("galaxy"), filters=filters) == (1, 3, 1, 0)
            assert await store.range_counts(buckets[:2]) == (2, 6)
            assert await store.range_counts([], filters=filters) == ()
            assert await store.range_counts(buckets[:1], query=Term("quasar")) == (0,)

    @pytest.mark.asyncio
    async def test_invalid_range_requests_raise_before_any_io(self, kind, tmp_path):
        async with open_store(kind, tmp_path / "never-created", facet_keys=("year",)) as store:
            with pytest.raises(ValueError, match="'authors' is not a facet key"):
                await store.range_counts([RangeFilter("authors", low="A")])
            with pytest.raises(ValueError, match="Only one filter per key"):
                await store.range_counts(
                    [RangeFilter("year", 2020)], filters=[RangeFilter("year", 2020), MetadataFilter("year", {"1"})]
                )
            with pytest.raises(ValueError, match="'authors' is not a facet key"):
                await store.filter_ids(filters=[RangeFilter("authors", low="A")])

    @pytest.mark.asyncio
    async def test_every_field_with_a_match_gets_a_snippet(self, kind, tmp_path):
        words = [f"w{index}" for index in range(60)]
        words[40] = "dwarf"
        document = SearchDocument("r1", title="Dwarf galaxies", abstract="Tidal streams", body=" ".join(words))
        async with open_store(kind, tmp_path) as store:
            await store.index([document])
            (hit,) = await store.search(parse_query("dwarf OR streams"))
            assert [snippet.field for snippet in hit.snippets] == ["title", "abstract", "body"]
            title, abstract, body = hit.snippets
            assert title == Snippet("title", "Dwarf galaxies", ((0, 5),))
            assert abstract == Snippet("abstract", "Tidal streams", ((6, 13),))
            assert body.text.startswith("…") and [body.text[start:end] for start, end in body.highlights] == ["dwarf"]
            assert (hit.snippet, hit.highlights) == (title.text, title.highlights)
            (scoped,) = await store.search(parse_query("body:dwarf"))
            assert [snippet.field for snippet in scoped.snippets] == ["body"]

    @pytest.mark.asyncio
    async def test_control_characters_are_stored_as_spaces(self, kind, tmp_path):
        async with open_store(kind, tmp_path) as store:
            await store.index([SearchDocument("r1", title="dwarf\x02galaxy\x03", body="a\x00b")])
            assert await store.get_documents(["r1"]) == {"r1": SearchDocument("r1", title="dwarf galaxy ", body="a b")}
            (hit,) = await store.search(Term("galaxy"))
            assert marked(hit) == ["galaxy"]


CORPUS = [
    SearchDocument(
        "1",
        title="Dwarf galaxies",
        abstract="H-alpha photometry of dwarf galaxies",
        body="We observe nearby dwarf galaxies with photometric surveys.",
    ),
    SearchDocument(
        "2",
        title="Quasar hosts",
        abstract="Quasar host galaxies",
        body="Photometry of quasar hosts and dwarf companions.",
    ),
    SearchDocument("3", title="Galaxy clusters", abstract="Cluster photometry", body="galaxy galaxy galaxy cluster"),
    SearchDocument(
        "4",
        title="Stellar streams",
        abstract="Streams around the Milky Way",
        body="Tidal streams from dwarf satellites.",
    ),
    SearchDocument("5", title="Müller's survey", abstract="A survey", body="Survey of galaxies"),
    SearchDocument("6", title="Unrelated", abstract="Nothing here", body="Filler text"),
]


@pytest.mark.parametrize(
    "query",
    [
        "galaxies",
        "dwarf galaxies",
        '"dwarf galaxies"',
        "photometr*",
        "title:galaxies",
        "abstract,body:dwarf",
        "dwarf -quasar",
        "quasar OR stream*",
        "(dwarf OR cluster) -title:quasar",
        "muller survey",
        "cluster OR (galaxy quasar)",
        "stream* OR (dwarf -satellites)",
        "survey OR (galax* photometr* quasar)",
    ],
)
@pytest.mark.asyncio
async def test_both_backends_rank_and_score_identically(query, tmp_path):
    node = parse_query(query)
    async with open_store("memory", tmp_path) as memory, open_store("fts5", tmp_path) as fts5:
        await memory.index(CORPUS)
        await fts5.index(CORPUS)
        expected = await memory.search(node)
        actual = await fts5.search(node)
        assert [hit.record_id for hit in actual] == [hit.record_id for hit in expected]
        assert [hit.score for hit in actual] == pytest.approx([hit.score for hit in expected], rel=1e-9)
