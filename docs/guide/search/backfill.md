# Backfilling from vector memory

A deployment that has run with semantic memory but no text index already holds
every relevant record's full text, split into chunks, in its
`AsyncSqliteEmbeddingStore`. `backfill_text_index` builds the text index from
those chunks, so nothing has to be fetched or embedded again:

```python
import asyncio

from sci_etl_core.embeddings import AsyncSqliteEmbeddingStore, SlidingWindowChunker
from sci_etl_core.search import AsyncSqliteFts5Store, backfill_text_index


async def backfill() -> None:
    vector_store = AsyncSqliteEmbeddingStore("memory.db")
    text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))
    try:
        report = await backfill_text_index(
            vector_store,
            text_store,
            overlap_words=SlidingWindowChunker().overlap_words,
        )
        print(f"{report.indexed} indexed, {report.skipped_existing} already there, {report.skipped_empty} empty")
    finally:
        await vector_store.aclose()
        await text_store.aclose()


asyncio.run(backfill())
```

Run it once, while no pipeline is writing to either store, and then add an
`AsyncSearchIndexer` to the pipeline as [Local search and discovery](index.md)
shows, so new records are indexed as they arrive.

## Overlapping chunks

`SlidingWindowChunker` overlaps neighbouring chunks, by 50 words by default, so
that no passage is cut off at a window boundary. Joining the chunks as they
are would repeat those words, and BM25 would count every word at a boundary
twice. The backfill removes the overlap with `merge_passages`, which drops the
first `overlap_words` words of each chunk when they repeat the end of the
chunk before, so the body comes back with every word once.

Pass the `overlap_words` of the chunker that wrote the chunks. With
`SlidingWindowChunker(chunk_words, overlap_words)`, pass the same
`overlap_words`; when you left it out, read it back from a chunker built the
same way, as the example does. A chunk whose first words don't repeat the
previous chunk's last words is kept whole, so a wrong value leaves the
repeated words in the body rather than cutting text out.

The body comes back with single spaces between words, as the chunker split
it; line breaks and paragraph spacing are gone, which doesn't change what
matches.

## What a backfilled document holds

The vector memory keeps less than the pipeline had, so by default a
backfilled document has:

| Field | Value |
|-------|-------|
| `title` | the `title` stored with the record's chunks |
| `abstract` | empty, since the chunks don't hold it |
| `body` | the chunks, merged |
| `metadata` | the other chunk metadata, such as `source_url` |

`AsyncChunkIngestor` doesn't store `RawRecord.metadata` with the chunks, so a
backfilled document has no `categories`, `year`, or other facet tags, and
filters on those keys don't match it. When you have that metadata elsewhere,
such as in the exported CSV, pass a `build_document` that adds it. It receives
the `StoredRecord` and the merged body, and returns the `SearchDocument` to
index, or `None` to leave the record out:

```python
from sci_etl_core.search import SearchDocument, backfill_text_index, stored_record_document


def with_catalogue_metadata(record, body):
    document = stored_record_document(record, body)
    if document is None or record.record_id not in catalogue:
        return document
    entry = catalogue[record.record_id]
    document.abstract = entry["abstract"]
    document.metadata.update(categories=entry["categories"], year=entry["year"])
    return document


report = await backfill_text_index(
    vector_store, text_store, overlap_words=50, build_document=with_catalogue_metadata
)
```

## Records already in the index

A record the pipeline already indexed has its abstract and metadata, which a
backfilled document lacks, so the backfill leaves it alone and counts it in
`skipped_existing`. Pass `replace_existing=True` to overwrite every record
from the vector memory, for example after rebuilding a text index from
scratch. Records in the text index that aren't in the vector memory are never
touched.

- **Batches.** Records are read and written `batch_size` at a time (default
  100), without loading any vector, so memory use stays flat on a large store.
- **Other vector stores.** `InMemoryEmbeddingStore` and
  `AsyncSqliteEmbeddingStore` can list their records through `iter_records`.
  A custom `AsyncEmbeddingStore` that doesn't implement it raises
  `NotImplementedError`.
- **Ownership.** `backfill_text_index` closes neither store; close them
  yourself, as the example does.
