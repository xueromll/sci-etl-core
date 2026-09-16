from __future__ import annotations

import asyncio
import math
import tempfile
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from sci_etl_core.embeddings._similarity import (
    l2_normalize,
    to_matrix,
    top_similarity,
    unit_vector,
)
from sci_etl_core.embeddings.chunking import SlidingWindowChunker
from sci_etl_core.embeddings.store_base import EmbeddingChunk
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.exceptions import SearchQueryError
from sci_etl_core.exporters.csv_async import AsyncCsvUpsertExporter
from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.parsers.reference_trimmer import trim_after_references
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.processors.dedup import DeduplicationStep, NeighborMatcher
from sci_etl_core.processors.normalization import DefaultKeyNormalizer, NormalizationStep
from sci_etl_core.processors.quality import CompletenessStep, QualityFlagStep
from sci_etl_core.processors.validation import (
    CompositeValidator,
    KeywordExclusionValidator,
    NumericRangeValidator,
)
from sci_etl_core.search.backfill_async import merge_passages
from sci_etl_core.search.compile_fts5 import is_rankable, to_filter_expression, to_match_expression
from sci_etl_core.search.edges import AsyncEdgeSource
from sci_etl_core.search.evaluate import matches
from sci_etl_core.search.filters import MetadataFilter, RangeFilter, matches_filters, split_markers, tag_rows
from sci_etl_core.search.fusion import reciprocal_rank_fusion
from sci_etl_core.search.graph import GraphEdge, GraphParams, build_discovery_graph, label_communities
from sci_etl_core.search.parser import parse_query
from sci_etl_core.search.query import And, Near, Not, Or, Phrase, Term, normalize
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_memory import InMemoryTextSearchStore
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store
from sci_etl_core.search.tokenize import Token, Unicode61Tokenizer
from sci_etl_core.state.async_file_state import AsyncFileStateManager

_EXTRACTOR = AsyncArxivExtractor(client=None, pdf_parser=None, latex_parser=None)
_NORMALIZER = DefaultKeyNormalizer()

_ARXIV_ID = st.from_regex(r"[0-9]{4}\.[0-9]{4,5}(v[0-9]+)?", fullmatch=True)
_NO_MARKER_TEXT = st.text(st.characters(blacklist_characters="\n\r\\"))

# Property tests that touch the filesystem create their own temp directory per
# example rather than taking pytest's function-scoped ``tmp_path``: a single
# test function runs many examples, so a per-function fixture would be shared
# across them and Hypothesis rightly rejects that.
_FS_SETTINGS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


class TestNormalizeIdProperties:
    @given(_ARXIV_ID)
    def test_bare_id_is_returned_unchanged(self, bare):
        assert _EXTRACTOR._normalize_id(bare) == bare

    @given(_ARXIV_ID)
    def test_abs_prefix_is_stripped(self, bare):
        assert _EXTRACTOR._normalize_id(f"http://arxiv.org/abs/{bare}") == bare

    @given(_ARXIV_ID)
    def test_pdf_prefix_and_suffix_are_stripped(self, bare):
        assert _EXTRACTOR._normalize_id(f"http://arxiv.org/pdf/{bare}.pdf") == bare

    @given(st.text())
    def test_result_never_retains_an_abs_marker(self, raw):
        assert "/abs/" not in _EXTRACTOR._normalize_id(raw)


class TestTrimAfterReferencesProperties:
    @given(st.text())
    def test_result_is_a_prefix_of_the_input(self, text):
        result = trim_after_references(text)
        assert text.startswith(result)

    @given(st.text())
    def test_result_is_never_longer_than_input(self, text):
        assert len(trim_after_references(text)) <= len(text)

    @given(_NO_MARKER_TEXT)
    def test_text_without_markers_is_unchanged(self, text):
        assert trim_after_references(text) == text

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_values_pass_through(self, empty):
        assert trim_after_references(empty) == empty


class TestDefaultKeyNormalizerProperties:
    @given(st.text())
    def test_output_contains_no_separators_punctuation_or_controls(self, raw):
        assert all(
            unicodedata.category(character)[0] in "LMNS"
            for character in _NORMALIZER.normalize(raw)
        )

    @given(st.text())
    def test_normalize_is_idempotent(self, raw):
        once = _NORMALIZER.normalize(raw)
        assert _NORMALIZER.normalize(once) == once

    @given(st.text())
    def test_output_is_stable_under_casefolding(self, raw):
        result = _NORMALIZER.normalize(raw)
        assert _NORMALIZER.normalize(result.casefold()) == result


_WIDE_COMPONENT = st.floats(
    min_value=-1e25, max_value=1e25, allow_nan=False, allow_infinity=False
)
_WIDE_VECTOR = st.lists(_WIDE_COMPONENT, min_size=1, max_size=8)


def _norm64(array: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(array, dtype=np.float64)))


class TestUnitVectorProperties:
    @given(_WIDE_VECTOR)
    def test_result_is_unit_length_or_a_genuine_zero_vector(self, vector):
        result = unit_vector(vector)
        if not np.asarray(vector, dtype=np.float32).any():
            assert not result.any()
        else:
            assert _norm64(result) == pytest.approx(1.0, rel=1e-4)

    @given(_WIDE_VECTOR)
    def test_result_is_always_finite(self, vector):
        assert np.isfinite(unit_vector(vector)).all()

    @given(_WIDE_VECTOR)
    def test_normalizing_twice_changes_nothing(self, vector):
        once = unit_vector(vector)
        assert unit_vector(once) == pytest.approx(once, rel=1e-4, abs=1e-7)

    @given(_WIDE_VECTOR)
    def test_no_component_ever_flips_sign(self, vector):
        """Scaling must not reverse a component's direction.

        A component may still land on zero: float32 flushes a denormal such as
        1e-45 to zero once it is divided by a much larger norm. That loses
        magnitude, never direction.
        """
        original = np.asarray(vector, dtype=np.float32)
        assume(original.any())
        result = unit_vector(vector)
        for scaled, source in zip(np.sign(result), np.sign(original), strict=True):
            assert scaled == source or scaled == 0.0

    @given(_WIDE_VECTOR, st.floats(min_value=1e-3, max_value=1e3, allow_nan=False))
    def test_positive_rescaling_does_not_change_the_unit_vector(self, vector, factor):
        original = np.asarray(vector, dtype=np.float32)
        assume(original.any())
        scaled = [component * factor for component in vector]
        assume(np.asarray(scaled, dtype=np.float32).any())
        assert unit_vector(scaled) == pytest.approx(unit_vector(vector), abs=1e-3)


class TestL2NormalizeProperties:
    @given(st.lists(st.lists(_WIDE_COMPONENT, min_size=1, max_size=6), min_size=1, max_size=6))
    def test_every_row_is_unit_length_or_zero(self, rows):
        width = len(rows[0])
        rows = [row[:width] + [0.0] * (width - len(row)) for row in rows]
        normalized = l2_normalize(to_matrix(rows))
        for row in normalized:
            norm = _norm64(row)
            assert norm == pytest.approx(1.0) or norm == 0.0


class TestTopSimilarityProperties:
    @given(st.lists(st.lists(_WIDE_COMPONENT, min_size=1, max_size=6), min_size=1, max_size=6))
    def test_score_never_leaves_the_cosine_range(self, rows):
        width = len(rows[0])
        rows = [row[:width] + [0.0] * (width - len(row)) for row in rows]
        references = l2_normalize(to_matrix(rows))
        score = top_similarity(rows[0], references)
        assert -1.0 - 1e-9 <= score <= 1.0 + 1e-9

    @given(st.lists(st.lists(_WIDE_COMPONENT, min_size=1, max_size=6), min_size=1, max_size=6))
    def test_a_vector_present_among_the_references_scores_near_one(self, rows):
        width = len(rows[0])
        rows = [row[:width] + [0.0] * (width - len(row)) for row in rows]
        query = rows[0]
        assume(_norm64(np.asarray(query, dtype=np.float64)) > 0.0)
        references = l2_normalize(to_matrix(rows))
        assert top_similarity(query, references) == pytest.approx(1.0, abs=1e-6)

    @given(st.lists(_WIDE_COMPONENT, min_size=1, max_size=6))
    def test_a_degenerate_query_never_reads_as_a_match(self, vector):
        references = l2_normalize(to_matrix([[1.0] * len(vector)]))
        zeros = [0.0] * len(vector)
        assert top_similarity(zeros, references) == -1.0
        assert top_similarity([], references) == -1.0


_DIM = 4
_STORE_COMPONENT = st.floats(
    min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False
)
_STORE_VECTOR = st.lists(_STORE_COMPONENT, min_size=_DIM, max_size=_DIM)

_CHUNK = st.builds(
    EmbeddingChunk,
    record_id=st.sampled_from(["a", "b", "c"]),
    chunk_index=st.integers(min_value=0, max_value=2),
    text=st.text(max_size=12),
    vector=_STORE_VECTOR,
    metadata=st.fixed_dictionaries({"title": st.text(max_size=8)}),
)
_CHUNKS = st.lists(_CHUNK, min_size=1, max_size=8)


@asynccontextmanager
async def _both_backends(chunks):
    """Yield an in-memory and a SQLite store holding the same chunks."""
    with tempfile.TemporaryDirectory() as directory:
        memory = InMemoryEmbeddingStore()
        sqlite = AsyncSqliteEmbeddingStore(Path(directory) / "vectors.db")
        try:
            await memory.add(chunks)
            await sqlite.add(chunks)
            yield memory, sqlite
        finally:
            await sqlite.aclose()


def _assert_obeys_query_contract(hits, chunks, top_k, min_score, exclude_record_id):
    assert len(hits) <= max(top_k, 0)
    assert [hit.score for hit in hits] == sorted(
        (hit.score for hit in hits), reverse=True
    )
    assert all(hit.score >= min_score for hit in hits)
    assert all(math.isfinite(hit.score) for hit in hits)
    assert all(hit.record_id != exclude_record_id for hit in hits)
    keys = [(hit.record_id, hit.chunk_index) for hit in hits]
    assert len(keys) == len(set(keys))
    stored = {(chunk.record_id, chunk.chunk_index) for chunk in chunks}
    assert set(keys) <= stored


class TestEmbeddingStoreProperties:
    @given(
        chunks=_CHUNKS,
        query=_STORE_VECTOR,
        top_k=st.integers(min_value=-2, max_value=6),
        min_score=st.floats(min_value=-1.0, max_value=1.0),
        exclude=st.one_of(st.none(), st.sampled_from(["a", "b", "c"])),
    )
    @_FS_SETTINGS
    def test_both_backends_obey_the_query_contract(
        self, chunks, query, top_k, min_score, exclude
    ):
        async def scenario():
            async with _both_backends(chunks) as (memory, sqlite):
                for store in (memory, sqlite):
                    hits = await store.query(query, top_k, min_score, exclude)
                    _assert_obeys_query_contract(
                        hits, chunks, top_k, min_score, exclude
                    )

        asyncio.run(scenario())

    @given(
        chunks=_CHUNKS,
        query=_STORE_VECTOR,
        top_k=st.integers(min_value=-2, max_value=6),
        min_score=st.floats(min_value=-1.0, max_value=1.0),
        exclude=st.one_of(st.none(), st.sampled_from(["a", "b", "c"])),
    )
    @_FS_SETTINGS
    def test_the_two_backends_return_the_same_scores(
        self, chunks, query, top_k, min_score, exclude
    ):
        """The stores are interchangeable, so a swap must not change results.

        Scores rather than identities are compared: when two chunks tie, the
        backends may legitimately break the tie in a different order.
        """

        async def scenario():
            async with _both_backends(chunks) as (memory, sqlite):
                from_memory = await memory.query(query, top_k, min_score, exclude)
                from_sqlite = await sqlite.query(query, top_k, min_score, exclude)
                assert len(from_memory) == len(from_sqlite)
                assert [hit.score for hit in from_memory] == pytest.approx(
                    [hit.score for hit in from_sqlite], rel=1e-4, abs=1e-6
                )

        asyncio.run(scenario())

    @given(chunks=_CHUNKS)
    @_FS_SETTINGS
    def test_adding_the_same_chunks_twice_stores_them_once(self, chunks):
        """``add`` replaces by ``(record_id, chunk_index)`` in both backends.

        Re-ingesting an article must not give it extra weight in the memory,
        which is what an append-only backend would silently do.
        """
        distinct = len({(chunk.record_id, chunk.chunk_index) for chunk in chunks})

        async def scenario():
            async with _both_backends(chunks) as (memory, sqlite):
                assert await memory.count() == distinct
                assert await sqlite.count() == distinct
                await memory.add(chunks)
                await sqlite.add(chunks)
                assert await memory.count() == distinct
                assert await sqlite.count() == distinct

        asyncio.run(scenario())

    @given(chunks=_CHUNKS, query=_STORE_VECTOR)
    @_FS_SETTINGS
    def test_a_zero_budget_returns_nothing_in_both_backends(self, chunks, query):
        async def scenario():
            async with _both_backends(chunks) as (memory, sqlite):
                for store in (memory, sqlite):
                    assert await store.query(query, top_k=0) == []
                    assert await store.query(query, top_k=-1) == []

        asyncio.run(scenario())

    @given(chunks=_CHUNKS)
    @_FS_SETTINGS
    def test_a_degenerate_query_matches_nothing_in_both_backends(self, chunks):
        async def scenario():
            async with _both_backends(chunks) as (memory, sqlite):
                for store in (memory, sqlite):
                    assert await store.query([0.0] * _DIM) == []
                    assert await store.query([]) == []
                    # A dimension mismatch is not a match either.
                    assert await store.query([1.0] * (_DIM + 1)) == []

        asyncio.run(scenario())


_TITLE = st.text(max_size=10)
_SCORE = st.one_of(
    st.none(),
    st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False),
)
_RECORDS = st.lists(
    st.fixed_dictionaries({"title": _TITLE, "score": _SCORE}),
    min_size=1,
    max_size=10,
)


def _normalized_frame(records):
    frame = pd.DataFrame(records)
    return NormalizationStep("title", _NORMALIZER).process(frame)


class TestDeduplicationProperties:
    @given(_RECORDS)
    def test_output_has_one_row_per_normalized_key(self, records):
        frame = _normalized_frame(records)
        result = DeduplicationStep("_norm_key").process(frame)
        keys = [key for key in result["_norm_key"].tolist() if key]
        assert len(keys) == len(set(keys))

    @given(_RECORDS)
    def test_rows_without_a_key_are_never_merged(self, records):
        frame = _normalized_frame(records)
        result = DeduplicationStep("_norm_key").process(frame)
        assert (result["_norm_key"] == "").sum() == (frame["_norm_key"] == "").sum()

    @given(_RECORDS)
    def test_no_key_is_invented_or_lost(self, records):
        frame = _normalized_frame(records)
        result = DeduplicationStep("_norm_key").process(frame)
        assert set(result["_norm_key"]) == set(frame["_norm_key"])

    @given(_RECORDS)
    def test_output_is_never_larger_than_input(self, records):
        frame = _normalized_frame(records)
        result = DeduplicationStep("_norm_key").process(frame)
        assert len(result) <= len(frame)

    @given(_RECORDS)
    def test_a_group_with_any_value_keeps_a_value(self, records):
        """Collapsing duplicates must not discard the only value in a group."""
        frame = _normalized_frame(records)
        result = DeduplicationStep("_norm_key").process(frame)
        survivors = result[result["_norm_key"] != ""].set_index("_norm_key")["score"]
        for key, group in frame[frame["_norm_key"] != ""].groupby("_norm_key"):
            if group["score"].notna().any():
                assert pd.notna(survivors.loc[key])

    @given(_RECORDS)
    def test_merging_a_matched_pair_only_fills_gaps(self, records):
        """A matcher may fill a kept row's blanks, never overwrite its values."""

        class _PairFirstTwo(NeighborMatcher):
            def find_matches(self, frame, threshold):
                return [(0, 1)] if len(frame) >= 2 else []

        frame = _normalized_frame(records)
        before = DeduplicationStep("_norm_key").process(frame)
        assume(len(before) >= 2)
        kept_score = before.at[0, "score"]

        after = DeduplicationStep("_norm_key", matcher=_PairFirstTwo()).process(frame)
        assert len(after) == len(before) - 1
        if pd.notna(kept_score):
            assert after.at[0, "score"] == kept_score
        else:
            filler = before.at[1, "score"]
            assert pd.isna(after.at[0, "score"]) or after.at[0, "score"] == filler


_CSV_KEY = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=' ,"-'
    ),
    min_size=1,
    max_size=8,
)
_CSV_RECORDS = st.lists(
    st.fixed_dictionaries(
        {
            "name": _CSV_KEY,
            "score": st.one_of(
                st.none(),
                st.floats(
                    min_value=-500.0,
                    max_value=500.0,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            ),
        }
    ),
    min_size=1,
    max_size=6,
)

_CLIP = (0.0, 100.0)


def _read_csv(destination: Path) -> pd.DataFrame:
    return pd.read_csv(
        destination, dtype={"name": str}, keep_default_na=False, na_values=[""]
    )


class TestCsvUpsertProperties:
    @given(first=_CSV_RECORDS, second=_CSV_RECORDS)
    @_FS_SETTINGS
    def test_an_existing_value_is_never_overwritten(self, first, second):
        """The exporter fills blanks only; a recorded value is final."""

        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "out.csv"
                exporter = AsyncCsvUpsertExporter(
                    "name", ["score"], _NORMALIZER, {"score": _CLIP}
                )
                await exporter.export(first, str(destination))
                after_first = _read_csv(destination)
                await exporter.export(second, str(destination))
                after_second = _read_csv(destination)

                settled = after_first.set_index(
                    after_first["name"].apply(_NORMALIZER.normalize)
                )["score"]
                final = after_second.set_index(
                    after_second["name"].apply(_NORMALIZER.normalize)
                )["score"]
                for key, value in settled.items():
                    if pd.notna(value):
                        assert final.loc[key] == pytest.approx(value)

        asyncio.run(scenario())

    @given(first=_CSV_RECORDS, second=_CSV_RECORDS)
    @_FS_SETTINGS
    def test_no_row_ever_disappears(self, first, second):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "out.csv"
                exporter = AsyncCsvUpsertExporter(
                    "name", ["score"], _NORMALIZER, {"score": _CLIP}
                )
                await exporter.export(first, str(destination))
                keys_before = set(
                    _read_csv(destination)["name"].apply(_NORMALIZER.normalize)
                )
                await exporter.export(second, str(destination))
                keys_after = set(
                    _read_csv(destination)["name"].apply(_NORMALIZER.normalize)
                )
                assert keys_before <= keys_after

        asyncio.run(scenario())

    @given(first=_CSV_RECORDS, second=_CSV_RECORDS)
    @_FS_SETTINGS
    def test_one_row_per_normalized_key(self, first, second):
        """An upsert keeps a single row per key, within a batch and across them.

        Records sharing a key inside one batch are the hard case: the pending
        rows are not yet in the frame that the match is looked up in.
        """

        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "out.csv"
                exporter = AsyncCsvUpsertExporter(
                    "name", ["score"], _NORMALIZER, {"score": _CLIP}
                )
                for batch in (first, second):
                    await exporter.export(batch, str(destination))
                    keys = [
                        _NORMALIZER.normalize(name)
                        for name in _read_csv(destination)["name"]
                    ]
                    assert len(keys) == len(set(keys))

        asyncio.run(scenario())

    @given(records=_CSV_RECORDS)
    @_FS_SETTINGS
    def test_every_written_value_respects_the_clip_bounds(self, records):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "out.csv"
                exporter = AsyncCsvUpsertExporter(
                    "name", ["score"], _NORMALIZER, {"score": _CLIP}
                )
                await exporter.export(records, str(destination))
                low, high = _CLIP
                for value in _read_csv(destination)["score"].dropna():
                    assert low <= float(value) <= high

        asyncio.run(scenario())

    @given(records=_CSV_RECORDS)
    @_FS_SETTINGS
    def test_reloading_the_file_preserves_every_key(self, records):
        """A fresh exporter over an existing file must reuse its rows.

        This is the crash-resume path. If a reloaded key no longer matches the
        record that produced it, the next run appends a second row for the same
        entity instead of filling the first.
        """

        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "out.csv"
                first = AsyncCsvUpsertExporter(
                    "name", ["score"], _NORMALIZER, {"score": _CLIP}
                )
                await first.export(records, str(destination))
                before = _read_csv(destination)

                # A brand-new exporter, as a restarted process would build.
                reloaded = AsyncCsvUpsertExporter(
                    "name", ["score"], _NORMALIZER, {"score": _CLIP}
                )
                await reloaded.export(records, str(destination))
                after = _read_csv(destination)

                assert list(after["name"]) == list(before["name"])

        asyncio.run(scenario())

    @given(records=_CSV_RECORDS)
    @_FS_SETTINGS
    def test_a_record_whose_key_normalizes_away_is_skipped(self, records):
        """Keys made only of punctuation carry no identity and must not persist."""

        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "out.csv"
                exporter = AsyncCsvUpsertExporter("name", ["score"], _NORMALIZER)
                blanks = [{"name": ",,,", "score": 1.0}, {"name": "", "score": 2.0}]
                await exporter.export(records + blanks, str(destination))
                written = _read_csv(destination)
                assert all(
                    _NORMALIZER.normalize(name) != "" for name in written["name"]
                )

        asyncio.run(scenario())


_RECORD_ID = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="._-/"
    ),
    min_size=1,
    max_size=12,
).filter(lambda value: value.strip() == value and value.strip() != "")


class TestFileStateProperties:
    @given(ids=st.lists(_RECORD_ID, max_size=10))
    @_FS_SETTINGS
    def test_processed_ids_round_trip(self, ids):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                state = AsyncFileStateManager(
                    Path(directory) / "ids.txt", Path(directory) / "meta.json"
                )
                for record_id in ids:
                    await state.mark_processed(record_id)
                assert await state.load_processed_ids() == set(ids)

        asyncio.run(scenario())

    @given(ids=st.lists(_RECORD_ID, max_size=10))
    @_FS_SETTINGS
    def test_marking_an_id_twice_changes_nothing(self, ids):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                state = AsyncFileStateManager(
                    Path(directory) / "ids.txt", Path(directory) / "meta.json"
                )
                for record_id in ids:
                    await state.mark_processed(record_id)
                once = await state.load_processed_ids()
                for record_id in ids:
                    await state.mark_processed(record_id)
                assert await state.load_processed_ids() == once

        asyncio.run(scenario())

    @given(
        prefix=_RECORD_ID,
        suffix=_RECORD_ID,
        separator=st.sampled_from(["\n", "\r", "\r\n"]),
    )
    @_FS_SETTINGS
    def test_an_id_containing_a_line_break_is_refused(self, prefix, suffix, separator):
        """One id per line: a break would be read back as several ids.

        Accepting it would mark records as processed that were never seen, so
        they would be skipped forever on later runs.
        """

        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                state = AsyncFileStateManager(
                    Path(directory) / "ids.txt", Path(directory) / "meta.json"
                )
                with pytest.raises(ValueError):
                    await state.mark_processed(f"{prefix}{separator}{suffix}")
                assert await state.load_processed_ids() == set()

        asyncio.run(scenario())

    @given(start_index=st.integers(min_value=0, max_value=10**6))
    @_FS_SETTINGS
    def test_metadata_round_trips(self, start_index):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                state = AsyncFileStateManager(
                    Path(directory) / "ids.txt", Path(directory) / "meta.json"
                )
                metadata = await state.load_metadata()
                metadata.last_start_index = start_index
                await state.save_metadata(metadata)
                reloaded = await state.load_metadata()
                assert reloaded.last_start_index == start_index
                assert reloaded.last_run_at is not None

        asyncio.run(scenario())


_LIMIT = st.one_of(st.none(), st.integers(min_value=1, max_value=10_000))


class TestResolveLimitsProperties:
    @given(page_size=_LIMIT, total_limit=_LIMIT, max_records=_LIMIT)
    def test_both_limits_are_always_resolved_to_positive_integers(
        self, page_size, total_limit, max_records
    ):
        resolved_page, resolved_total = AsyncETLPipeline._resolve_limits(
            page_size, total_limit, max_records
        )
        assert isinstance(resolved_page, int) and resolved_page > 0
        assert isinstance(resolved_total, int) and resolved_total > 0

    @given(page_size=_LIMIT, total_limit=_LIMIT, max_records=_LIMIT)
    def test_an_explicit_limit_is_never_overridden(
        self, page_size, total_limit, max_records
    ):
        resolved_page, resolved_total = AsyncETLPipeline._resolve_limits(
            page_size, total_limit, max_records
        )
        if page_size is not None:
            assert resolved_page == page_size
        if total_limit is not None:
            assert resolved_total == total_limit

    @given(max_records=st.integers(min_value=1, max_value=10_000))
    def test_the_max_records_alias_seeds_both_limits(self, max_records):
        assert AsyncETLPipeline._resolve_limits(None, None, max_records) == (
            max_records,
            max_records,
        )

    @given(page_size=st.integers(min_value=1, max_value=10_000))
    def test_a_lone_page_size_becomes_the_whole_budget(self, page_size):
        assert AsyncETLPipeline._resolve_limits(page_size, None, None) == (
            page_size,
            page_size,
        )


_TRACKED = ["alpha", "beta", "gamma", "delta"]
_CELL = st.one_of(st.none(), st.text(min_size=1, max_size=4))
_QUALITY_ROWS = st.lists(
    st.fixed_dictionaries({field: _CELL for field in _TRACKED}),
    min_size=1,
    max_size=8,
)


class TestQualityProperties:
    @given(_QUALITY_ROWS)
    def test_completeness_stays_within_zero_and_one_hundred(self, rows):
        frame = CompletenessStep(_TRACKED).process(pd.DataFrame(rows))
        assert frame["completeness_pct"].between(0.0, 100.0).all()

    @given(_QUALITY_ROWS, st.integers(min_value=0, max_value=3))
    def test_filling_a_field_never_lowers_completeness(self, rows, field_index):
        field = _TRACKED[field_index]
        before = CompletenessStep(_TRACKED).process(pd.DataFrame(rows))
        filled = pd.DataFrame(rows)
        filled[field] = filled[field].fillna("x")
        after = CompletenessStep(_TRACKED).process(filled)
        assert (after["completeness_pct"] >= before["completeness_pct"]).all()

    @given(_QUALITY_ROWS)
    def test_only_a_fully_populated_row_is_confirmed(self, rows):
        frame = pd.DataFrame(rows)
        scored = CompletenessStep(_TRACKED).process(frame)
        flagged = QualityFlagStep().process(scored)
        for position, flag in enumerate(flagged["quality_flag"]):
            if flag == "Confirmed":
                assert frame.iloc[position][_TRACKED].notna().all()

    @given(_QUALITY_ROWS)
    def test_every_row_receives_a_known_flag(self, rows):
        scored = CompletenessStep(_TRACKED).process(pd.DataFrame(rows))
        flagged = QualityFlagStep().process(scored)
        assert set(flagged["quality_flag"]) <= {
            "Confirmed",
            "Needs Review",
            "Low Confidence",
        }


_BOUND = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)


class TestNumericRangeValidatorProperties:
    @given(low=_BOUND, high=_BOUND, value=_BOUND)
    def test_membership_decides_the_verdict(self, low, high, value):
        assume(low <= high)
        validator = NumericRangeValidator({"n": (low, high)})
        assert validator.is_valid({"n": value}) is (low <= value <= high)

    @given(low=_BOUND, high=_BOUND)
    def test_a_missing_field_is_not_a_violation(self, low, high):
        validator = NumericRangeValidator({"n": (low, high)})
        assert validator.is_valid({}) is True
        assert validator.is_valid({"n": None}) is True

    @given(
        low=_BOUND,
        high=_BOUND,
        value=st.sampled_from([float("nan"), "abc", [], {}, object()]),
    )
    def test_an_uncomparable_value_is_rejected(self, low, high, value):
        assume(low <= high)
        validator = NumericRangeValidator({"n": (low, high)})
        assert validator.is_valid({"n": value}) is False

    @given(low=_BOUND, high=_BOUND, value=_BOUND)
    def test_a_composite_agrees_with_all_of_its_parts(self, low, high, value):
        assume(low <= high)
        parts = [
            NumericRangeValidator({"n": (low, high)}),
            NumericRangeValidator({"n": (low - 1.0, high + 1.0)}),
        ]
        record = {"n": value}
        assert CompositeValidator(parts).is_valid(record) is all(
            part.is_valid(record) for part in parts
        )


_WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=6)
_NULL_LIKE = {"null", "none", "unknown", "n/a", "nan", ""}


class TestKeywordExclusionValidatorProperties:
    @given(forbidden=st.lists(_WORD, max_size=4), filler=_WORD)
    def test_a_record_carrying_a_forbidden_token_is_rejected(self, forbidden, filler):
        assume(forbidden)
        banned = forbidden[0]
        validator = KeywordExclusionValidator("name", forbidden)
        assert validator.is_valid({"name": f"{filler} {banned}"}) is False

    @given(forbidden=st.lists(_WORD, max_size=4), value=_WORD)
    def test_a_clean_record_survives(self, forbidden, value):
        assume(value not in set(forbidden))
        assume(value not in _NULL_LIKE)
        validator = KeywordExclusionValidator("name", forbidden)
        assert validator.is_valid({"name": value}) is True

    @given(
        forbidden=st.lists(_WORD, max_size=4),
        null_like=st.sampled_from(sorted(_NULL_LIKE) + ["  ", "NULL", "N/A"]),
    )
    def test_a_null_like_value_is_always_rejected(self, forbidden, null_like):
        validator = KeywordExclusionValidator("name", forbidden)
        assert validator.is_valid({"name": null_like}) is False

    @given(value=st.text(max_size=10))
    def test_an_empty_ban_list_only_filters_null_like_values(self, value):
        validator = KeywordExclusionValidator("name", [])
        expected = value.strip().lower() not in _NULL_LIKE
        assert validator.is_valid({"name": value}) is expected


_QUERY_PIECES = st.sampled_from(
    [
        "a", "Bé", "H-alpha", "and", "AND", "OR", "NOT", "&&", "||", "-", "(", ")", '"', "*", "~", ",", ":",
        "title:", "Title,body:", "titel:", " ", "\t", "́", "NEAR(", "NEAR", ", 2)", "0", "title:NEAR(",
    ]
)
_QUERY_TEXT = st.one_of(st.text(max_size=40), st.lists(_QUERY_PIECES, max_size=24).map("".join))


class TestParseQueryProperties:
    @given(_QUERY_TEXT)
    def test_returns_a_normalized_node_or_a_located_query_error(self, text):
        try:
            node = parse_query(text)
        except SearchQueryError as error:
            assert error.position is not None
            assert 0 <= error.position <= len(text)
            assert text[error.position : error.position + len(error.token)] == error.token
        else:
            assert normalize(node) == node


_TOKENIZER = Unicode61Tokenizer()
_PARITY_TEXT = st.text(
    alphabet=st.one_of(
        st.sampled_from("AaZzßẞÆæØøŁłÉéÖöÜüİıΣσςЖж019-~.'́̈ \t\n\x00\x02"),
        st.characters(exclude_categories=("Cs",)),
    ),
    max_size=40,
)


class TestUnicode61TokenizerProperties:
    @given(texts=st.lists(_PARITY_TEXT, min_size=1, max_size=8))
    @settings(deadline=None)
    def test_yields_exactly_the_terms_fts5_indexes(self, texts, fts5_terms):
        assert [[token.text for token in _TOKENIZER.tokens(text)] for text in texts] == fts5_terms(texts)

    @given(st.text())
    def test_each_token_is_one_whole_word_at_its_offsets(self, text):
        previous_end = 0
        for token in _TOKENIZER.tokens(text):
            assert previous_end <= token.start < token.end <= len(text)
            word = text[token.start : token.end]
            assert _TOKENIZER.tokens(word) == [Token(token.text, 0, len(word))]
            previous_end = token.end


_QUERY_WORDS = ["a", "b", "c", "Bé", "ab", "alpha", "h alpha", "mull", "~", 'a"b', "c\x00d"]
_FIELD_SCOPES = [(), ("title",), ("abstract", "body")]
_NEAR_OPERAND = st.one_of(
    st.builds(Term, st.sampled_from(_QUERY_WORDS), st.just(()), st.booleans()),
    st.builds(Phrase, st.lists(st.sampled_from(_QUERY_WORDS), min_size=1, max_size=2).map(tuple)),
)
_LEAF = st.one_of(
    st.builds(Term, st.sampled_from(_QUERY_WORDS), st.sampled_from(_FIELD_SCOPES), st.booleans()),
    st.builds(
        Phrase,
        st.lists(st.sampled_from(_QUERY_WORDS), min_size=1, max_size=3).map(tuple),
        st.sampled_from(_FIELD_SCOPES),
    ),
    st.builds(
        Near,
        st.lists(_NEAR_OPERAND, min_size=2, max_size=4).map(tuple),
        st.integers(min_value=0, max_value=3),
        st.sampled_from(_FIELD_SCOPES),
    ),
)
_TREE = st.recursive(
    _LEAF,
    lambda children: st.one_of(
        st.builds(Not, children),
        st.builds(lambda kept, removed: And((kept, Not(removed))), children, children),
        st.lists(children, min_size=1, max_size=4).map(lambda operands: And(tuple(operands))),
        st.lists(children, min_size=1, max_size=4).map(lambda operands: Or(tuple(operands))),
    ),
    max_leaves=16,
)
_CORPUS_WORDS = ["a", "B", "c", "bé", "ab", "H-alpha", "Müller", "c~d", "~"]
_FIELD_TEXT = st.lists(st.sampled_from(_CORPUS_WORDS), max_size=5).map(" ".join)
_ROWS = st.lists(st.tuples(_FIELD_TEXT, _FIELD_TEXT, _FIELD_TEXT), min_size=1, max_size=5)


def _documents(rows):
    return [SearchDocument(str(index), *row) for index, row in enumerate(rows)]


def _subtrees(node):
    yield node
    if isinstance(node, Not):
        yield from _subtrees(node.operand)
    elif isinstance(node, (And, Or)):
        for operand in node.operands:
            yield from _subtrees(operand)


class TestNormalizeProperties:
    @given(_TREE)
    def test_normalizing_twice_changes_nothing(self, tree):
        once = normalize(tree)
        assert normalize(once) == once

    @given(_TREE)
    def test_the_result_has_canonical_shape(self, tree):
        for node in _subtrees(normalize(tree)):
            if isinstance(node, Not):
                assert not isinstance(node.operand, Not)
            if isinstance(node, (And, Or)):
                assert len(node.operands) >= 2
                assert not any(isinstance(operand, type(node)) for operand in node.operands)
            if isinstance(node, And):
                assert sum(isinstance(operand, Not) for operand in node.operands) <= 1

    @given(tree=_TREE, rows=_ROWS)
    def test_the_result_matches_exactly_the_documents_the_tree_matches(self, tree, rows):
        for document in _documents(rows):
            assert matches(normalize(tree), document) is matches(tree, document)


class TestCompileFts5Properties:
    @given(tree=_TREE, rows=_ROWS)
    @settings(deadline=None, max_examples=200)
    def test_fts5_returns_exactly_the_documents_matches_accepts(self, tree, rows, fts5_match):
        documents = _documents(rows)
        if not is_rankable(tree):
            with pytest.raises(SearchQueryError):
                to_match_expression(tree)
            return
        expected = {document.record_id for document in documents if matches(tree, document)}
        assert fts5_match(documents, to_match_expression(tree)) == expected

    @given(tree=_TREE, rows=_ROWS)
    @settings(deadline=None, max_examples=200)
    def test_the_filter_expression_selects_exactly_the_documents_matches_accepts(self, tree, rows, fts5_filter):
        documents = _documents(rows)
        expected = {document.record_id for document in documents if matches(tree, document)}
        assert fts5_filter(documents, *to_filter_expression(tree)) == expected

    @given(text=_QUERY_TEXT, rows=_ROWS)
    @settings(deadline=None)
    def test_a_rankable_parsed_query_runs_on_fts5_as_matches_evaluates_it(self, text, rows, fts5_match):
        try:
            node = parse_query(text)
        except SearchQueryError:
            return
        if is_rankable(node):
            documents = _documents(rows)
            expected = {document.record_id for document in documents if matches(node, document)}
            assert fts5_match(documents, to_match_expression(node)) == expected


@asynccontextmanager
async def _both_text_stores():
    """Yield an in-memory and an FTS5 text search store, both empty."""
    with tempfile.TemporaryDirectory() as directory:
        fts5 = AsyncSqliteFts5Store(Path(directory) / "search.db")
        try:
            yield InMemoryTextSearchStore(), fts5
        finally:
            await fts5.aclose()


def _query_words(tree):
    words: set[str] = set()
    stems: set[str] = set()
    for node in _subtrees(tree):
        if isinstance(node, Term):
            tokens = [token.text for token in _TOKENIZER.tokens(node.text)]
            if node.prefix and tokens:
                stems.add(tokens.pop())
            words.update(tokens)
        elif isinstance(node, Phrase):
            words.update(token.text for token in _TOKENIZER.tokens(" ".join(node.words)))
        elif isinstance(node, Near):
            operand_words, operand_stems = _query_words(Or(node.operands))
            words.update(operand_words)
            stems.update(operand_stems)
    return words, stems


def _assert_highlights_cover_query_words(hit, words, stems):
    previous_end = 0
    for start, end in hit.highlights:
        assert previous_end <= start < end <= len(hit.snippet)
        for token in _TOKENIZER.tokens(hit.snippet[start:end]):
            assert token.text in words or any(token.text.startswith(stem) for stem in stems)
        previous_end = end


class TestTextSearchStoreProperties:
    @given(tree=_TREE, rows=_ROWS)
    @_FS_SETTINGS
    def test_both_backends_match_rank_and_highlight_alike(self, tree, rows):
        documents = _documents(rows)

        async def scenario():
            async with _both_text_stores() as (memory, fts5):
                await memory.index(documents)
                await fts5.index(documents)
                assert await memory.filter_ids(tree) == await fts5.filter_ids(tree)
                if not is_rankable(tree):
                    for store in (memory, fts5):
                        with pytest.raises(SearchQueryError):
                            await store.search(tree)
                    return
                limit = await fts5.count() + 1
                expected = await memory.search(tree, limit)
                actual = await fts5.search(tree, limit)
                assert sorted(hit.record_id for hit in actual) == sorted(hit.record_id for hit in expected)
                words, stems = _query_words(tree)
                for hit in (*expected, *actual):
                    _assert_highlights_cover_query_words(hit, words, stems)

        asyncio.run(scenario())


_TAG_VALUE = st.one_of(
    st.text(max_size=3), st.integers(min_value=-3, max_value=3), st.booleans(), st.floats(allow_nan=False), st.none()
)
_METADATA = st.dictionaries(
    st.sampled_from(["a", "b", "c"]),
    st.one_of(_TAG_VALUE, st.lists(_TAG_VALUE, max_size=4), st.tuples(_TAG_VALUE, _TAG_VALUE)),
    max_size=3,
)


class TestTagRowsProperties:
    @given(metadata=_METADATA, keys=st.lists(st.sampled_from(["a", "b", "c", "d"]), max_size=5))
    def test_rows_never_repeat_and_are_sorted_within_each_key(self, metadata, keys):
        rows = tag_rows(metadata, keys)
        assert len(rows) == len(set(rows))
        assert list(rows) == sorted(rows)
        assert all(isinstance(value, str) and value for _key, value in rows)


_RANGE_TAG = st.one_of(
    st.integers(min_value=-12, max_value=12),
    st.sampled_from(["2019", "2020-05", "2020-05-31T23:00", "2021", "abc", "-0", "07", "+3", "", "é"]),
    st.integers(min_value=-12, max_value=12).map(str),
)
_RANGE_DOCUMENTS = st.lists(
    st.one_of(_RANGE_TAG, st.lists(_RANGE_TAG, max_size=3), st.none()), min_size=1, max_size=8
).map(
    lambda values: [
        SearchDocument(f"r{index}", title="galaxy", metadata={} if value is None else {"k": value})
        for index, value in enumerate(values)
    ]
)
_INT_BOUND = st.one_of(st.none(), st.integers(min_value=-15, max_value=15))
_TEXT_BOUND = st.one_of(st.none(), st.sampled_from(["2019", "2020", "2020-05", "2020-05-31", "21", "a", "é", "-", "0"]))


@st.composite
def _range_filters(draw):
    bounds = draw(st.one_of(st.tuples(_INT_BOUND, _INT_BOUND), st.tuples(_TEXT_BOUND, _TEXT_BOUND)))
    try:
        return RangeFilter("k", *bounds, negated=draw(st.booleans()))
    except ValueError:
        assume(False)


class TestRangeFilterProperties:
    @given(documents=_RANGE_DOCUMENTS, ranges=st.lists(_range_filters(), min_size=1, max_size=3))
    @_FS_SETTINGS
    def test_both_backends_select_and_count_the_same_records_as_matches_filters(self, documents, ranges):
        expected = [
            frozenset(
                document.record_id for document in documents if matches_filters(document.metadata, [search_range])
            )
            for search_range in ranges
        ]

        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                fts5 = AsyncSqliteFts5Store(Path(directory) / "search.db", facet_keys=("k",))
                memory = InMemoryTextSearchStore(facet_keys=("k",))
                try:
                    for store in (memory, fts5):
                        await store.index(documents)
                        assert [await store.filter_ids(None, [search_range]) for search_range in ranges] == expected
                        assert await store.range_counts(ranges, filters=[MetadataFilter("k", {"x"})]) == tuple(
                            len(ids) for ids in expected
                        )
                finally:
                    await fts5.aclose()

        asyncio.run(scenario())

    @given(value=_RANGE_TAG.map(str), search_range=_range_filters())
    def test_an_integer_range_only_ever_contains_tags_that_read_back_as_the_same_integer(self, value, search_range):
        bound = search_range.low if search_range.low is not None else search_range.high
        if isinstance(bound, int) and search_range.contains(value):
            assert str(int(value)) == value


class TestMergePassagesProperties:
    @given(
        words=st.lists(
            st.text(st.characters(exclude_categories=("Cs", "Zs", "Cc")), min_size=1, max_size=3), max_size=60
        ),
        chunk_words=st.integers(min_value=1, max_value=12),
        data=st.data(),
    )
    def test_the_passages_of_a_sliding_window_chunker_merge_back_into_the_text(self, words, chunk_words, data):
        overlap_words = data.draw(st.integers(min_value=0, max_value=chunk_words - 1))
        text = " ".join(words)
        assume(text.split() == words)
        passages = SlidingWindowChunker(chunk_words, overlap_words).chunk(text)
        assert merge_passages(passages, overlap_words) == text


_RANKED_LISTS = st.lists(
    st.lists(st.sampled_from("abcdefg"), max_size=6).map(lambda ids: [(record_id, 0.0) for record_id in ids]),
    max_size=4,
)


class TestReciprocalRankFusionProperties:
    @given(lists=_RANKED_LISTS, data=st.data())
    def test_the_order_of_the_lists_never_changes_the_result(self, lists, data):
        assert reciprocal_rank_fusion(data.draw(st.permutations(lists))) == reciprocal_rank_fusion(lists)

    @given(lists=_RANKED_LISTS, data=st.data())
    def test_moving_a_record_up_a_list_raises_its_fused_score(self, lists, data):
        assume(lists)
        index = data.draw(st.integers(min_value=0, max_value=len(lists) - 1))
        distinct = list(dict.fromkeys(record_id for record_id, _score in lists[index]))
        assume(len(distinct) >= 2)
        position = data.draw(st.integers(min_value=1, max_value=len(distinct) - 1))
        promoted = [*distinct[: position - 1], distinct[position], distinct[position - 1], *distinct[position + 1 :]]
        moved = distinct[position]
        changed = [*lists[:index], [(record_id, 0.0) for record_id in promoted], *lists[index + 1 :]]
        assert dict(reciprocal_rank_fusion(changed))[moved] > dict(reciprocal_rank_fusion(lists))[moved]


_GRAPH_IDS = [f"n{index}" for index in range(8)]


class _TableEdgeSource(AsyncEdgeSource):
    def __init__(self, table):
        self.table = table

    @property
    def kind(self):
        return "semantic"

    async def neighbours(self, record_ids, limit):
        return {record_id: self.table.get(record_id, []) for record_id in record_ids}


class TestDiscoveryGraphProperties:
    @given(
        table=st.dictionaries(
            st.sampled_from(_GRAPH_IDS),
            st.lists(st.tuples(st.sampled_from(_GRAPH_IDS), st.floats(min_value=0.0, max_value=1.0)), max_size=6),
        ),
        seed=st.sampled_from(_GRAPH_IDS),
        depth=st.integers(min_value=0, max_value=3),
        fanout=st.integers(min_value=1, max_value=4),
        max_nodes=st.integers(min_value=1, max_value=8),
        mutual_only=st.booleans(),
    )
    @settings(deadline=None)
    def test_no_edge_leaves_the_nodes_and_the_node_cap_holds(self, table, seed, depth, fanout, max_nodes, mutual_only):
        params = GraphParams(depth=depth, fanout=fanout, max_nodes=max_nodes, mutual_only=mutual_only)
        graph = asyncio.run(
            build_discovery_graph(seed, [_TableEdgeSource(table)], InMemoryTextSearchStore(), params=params)
        )
        ids = [node.record_id for node in graph.nodes]
        assert ids[0] == seed
        assert len(ids) == len(set(ids)) <= max_nodes
        assert all(edge.source in ids and edge.target in ids and edge.source < edge.target for edge in graph.edges)


_COMMUNITY_EDGES = st.lists(
    st.tuples(st.sampled_from(_GRAPH_IDS), st.sampled_from(_GRAPH_IDS), st.sampled_from([0.5, 1.0, 2.0])),
    max_size=20,
)


class TestLabelCommunitiesProperties:
    @given(pairs=_COMMUNITY_EDGES, extra=st.lists(st.sampled_from(_GRAPH_IDS), max_size=3), data=st.data())
    def test_communities_do_not_depend_on_input_order_or_spare_passes(self, pairs, extra, data):
        nodes = sorted({*extra, *(record_id for pair in pairs for record_id in pair[:2])})
        edges = [GraphEdge(first, second, weight, "semantic") for first, second, weight in pairs]
        expected = label_communities(nodes, edges)
        shuffled_nodes = data.draw(st.permutations(nodes))
        shuffled_edges = data.draw(st.permutations(edges))
        assert label_communities(shuffled_nodes, shuffled_edges) == expected
        communities, converged = expected
        if converged:
            assert label_communities(nodes, edges, max_iterations=40) == expected


class TestSplitMarkersProperties:
    @given(st.one_of(st.text(alphabet=st.sampled_from("ab \x02\x03…"), max_size=30), st.text(max_size=30)))
    def test_never_raises_and_every_span_lies_within_the_plain_text(self, raw):
        plain, spans = split_markers(raw)
        assert "\x02" not in plain and "\x03" not in plain
        previous_end = 0
        for start, end in spans:
            assert previous_end <= start < end <= len(plain)
            previous_end = end
