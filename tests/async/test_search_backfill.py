from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from sci_etl_core.embeddings.chunking import SlidingWindowChunker
from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, EmbeddingChunk, StoredRecord
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.search.backfill_async import (
    BackfillReport,
    backfill_text_index,
    merge_passages,
    stored_record_document,
)
from sci_etl_core.search.parser import parse_query
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_memory import InMemoryTextSearchStore
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store

ARTICLE = " ".join([*(f"w{index}" for index in range(23)), "dwarf", "galaxies", *(f"v{index}" for index in range(9))])


@asynccontextmanager
async def open_stores(vector_kind, text_kind, directory):
    vectors = InMemoryEmbeddingStore() if vector_kind == "memory" else AsyncSqliteEmbeddingStore(directory / "m.db")
    text = InMemoryTextSearchStore() if text_kind == "memory" else AsyncSqliteFts5Store(directory / "s.db")
    try:
        yield vectors, text
    finally:
        await vectors.aclose()
        await text.aclose()


def chunks_of(record_id, text, chunker, **metadata):
    return [
        EmbeddingChunk(record_id, index, passage, [1.0, 0.0], dict(metadata))
        for index, passage in enumerate(chunker.chunk(text))
    ]


class TestMergePassages:
    @pytest.mark.parametrize("chunk_words, overlap_words", [(10, 3), (10, 0), (5, 4), (40, 10), (1, 0)])
    def test_rebuilds_the_text_a_sliding_window_chunker_split(self, chunk_words, overlap_words):
        passages = SlidingWindowChunker(chunk_words, overlap_words).chunk(ARTICLE)
        assert merge_passages(passages, overlap_words) == ARTICLE

    def test_passages_that_do_not_repeat_the_previous_words_are_kept_whole(self):
        assert merge_passages(["a b c", "d e f"], 2) == "a b c d e f"

    def test_a_passage_no_longer_than_the_overlap_is_kept_whole(self):
        assert merge_passages(["a b", "a b"], 2) == "a b a b"
        assert merge_passages(["a", "a b"], 2) == "a a b"

    def test_whitespace_is_normalized_and_no_passages_give_empty_text(self):
        assert merge_passages(["a\tb\n", "b  c "], 1) == "a b c"
        assert merge_passages([], 3) == ""

    def test_a_negative_overlap_is_rejected(self):
        with pytest.raises(ValueError, match="overlap_words must not be negative"):
            merge_passages(["a"], -1)


class TestStoredRecordDocument:
    def test_takes_the_title_from_the_chunk_metadata_and_keeps_the_rest_as_metadata(self):
        record = StoredRecord("r1", ("x",), {"title": "Dwarf galaxies", "source_url": "https://example.org/r1"})
        assert stored_record_document(record, "body text") == SearchDocument(
            "r1", title="Dwarf galaxies", body="body text", metadata={"source_url": "https://example.org/r1"}
        )

    @pytest.mark.parametrize("title", [None, 7, "  "])
    def test_a_title_that_is_not_text_is_left_empty(self, title):
        record = StoredRecord("r1", ("x",), {"title": title})
        assert stored_record_document(record, "body") == SearchDocument("r1", body="body")

    def test_a_record_with_a_blank_title_and_body_gives_none(self):
        assert stored_record_document(StoredRecord("r1", ("  ",), {"title": ""}), "   ") is None


@pytest.mark.parametrize("vector_kind", ["memory", "sqlite"])
@pytest.mark.parametrize("text_kind", ["memory", "fts5"])
class TestBackfillTextIndex:
    @pytest.mark.asyncio
    async def test_indexes_each_record_with_its_overlap_removed(self, vector_kind, text_kind, tmp_path):
        chunker = SlidingWindowChunker(10, 4)
        async with open_stores(vector_kind, text_kind, tmp_path) as (vectors, text):
            await vectors.add(chunks_of("r1", ARTICLE, chunker, title="Dwarf galaxies", source_url="u1"))
            await vectors.add(chunks_of("r2", "tidal streams", chunker, title="Streams"))
            report = await backfill_text_index(vectors, text, overlap_words=chunker.overlap_words)
            assert report == BackfillReport(indexed=2)
            assert await text.get_documents(["r1", "r2"]) == {
                "r1": SearchDocument("r1", title="Dwarf galaxies", body=ARTICLE, metadata={"source_url": "u1"}),
                "r2": SearchDocument("r2", title="Streams", body="tidal streams"),
            }
            (hit,) = await text.search(parse_query('body:"dwarf galaxies"'))
            assert hit.record_id == "r1"

    @pytest.mark.asyncio
    async def test_records_already_indexed_are_left_alone_unless_replaced(self, vector_kind, text_kind, tmp_path):
        async with open_stores(vector_kind, text_kind, tmp_path) as (vectors, text):
            indexed = SearchDocument("r1", "Title", "The abstract", "Full text", {"year": "2024"})
            await text.index([indexed])
            await vectors.add([EmbeddingChunk("r1", 0, "chunk text", [1.0], {"title": "Title"})])
            await vectors.add([EmbeddingChunk("r2", 0, "other text", [1.0], {"title": "Other"})])
            assert await backfill_text_index(vectors, text, overlap_words=0) == BackfillReport(1, 1, 0)
            assert (await text.get_documents(["r1"]))["r1"] == indexed
            assert await backfill_text_index(vectors, text, overlap_words=0, replace_existing=True) == BackfillReport(2)
            assert (await text.get_documents(["r1"]))["r1"] == SearchDocument("r1", title="Title", body="chunk text")

    @pytest.mark.asyncio
    async def test_a_custom_builder_adds_metadata_or_leaves_records_out(self, vector_kind, text_kind, tmp_path):
        years = {"r1": "2024"}

        def with_year(record, body):
            if record.record_id not in years:
                return None
            return SearchDocument(record.record_id, body=body, metadata={"year": years[record.record_id]})

        async with open_stores(vector_kind, text_kind, tmp_path) as (vectors, text):
            await vectors.add([EmbeddingChunk(record_id, 0, "text", [1.0], {}) for record_id in ("r1", "r2")])
            report = await backfill_text_index(vectors, text, overlap_words=0, build_document=with_year)
            assert report == BackfillReport(indexed=1, skipped_empty=1)
            assert await text.get_documents(["r1", "r2"]) == {
                "r1": SearchDocument("r1", body="text", metadata={"year": "2024"})
            }


@pytest.mark.asyncio
async def test_documents_are_written_in_batches(mocker):
    vectors = InMemoryEmbeddingStore()
    await vectors.add([EmbeddingChunk(f"r{index}", 0, "text", [1.0], {}) for index in range(5)])
    await vectors.add([EmbeddingChunk("blank", 0, "  ", [1.0], {})])
    text = InMemoryTextSearchStore()
    index = mocker.spy(text, "index")
    report = await backfill_text_index(vectors, text, overlap_words=0, batch_size=2)
    assert report == BackfillReport(indexed=5, skipped_empty=1)
    assert [len(call.args[0]) for call in index.call_args_list] == [2, 2, 1]
    assert await text.count() == 5


@pytest.mark.parametrize(
    "options, message",
    [({"overlap_words": -1}, "overlap_words must not be negative"), ({"batch_size": 0}, "batch_size must be")],
)
@pytest.mark.asyncio
async def test_invalid_arguments_raise_before_any_io(mocker, options, message):
    vectors = InMemoryEmbeddingStore()
    text = InMemoryTextSearchStore()
    read = mocker.spy(text, "filter_ids")
    with pytest.raises(ValueError, match=message):
        await backfill_text_index(vectors, text, **{"overlap_words": 0, **options})
    assert read.call_count == 0


@pytest.mark.asyncio
async def test_a_vector_store_that_cannot_enumerate_its_records_is_reported():
    class VectorsOnly(AsyncEmbeddingStore):
        async def add(self, chunks):
            return None

        async def delete_record(self, record_id):
            return None

        async def query(self, vector, top_k=5, min_score=-1.0, exclude_record_id=None):
            return []

        async def count(self):
            return 0

    with pytest.raises(NotImplementedError, match="cannot enumerate"):
        await backfill_text_index(VectorsOnly(), InMemoryTextSearchStore(), overlap_words=0)
