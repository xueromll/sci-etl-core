# Local search and discovery

A text index next to the vector memory adds Boolean search, hybrid search that
fuses keyword and meaning-based rankings, metadata facets, and graphs of
related papers. All of it lives in `sci_etl_core.search` and needs only the
standard library's `sqlite3`, so it works on a bare `pip install sci-etl-core`.
The `search` extra installs nothing; it only lets a requirements file say why
the package is there. Only the semantic side needs the `embeddings` extra.

## Indexing from the pipeline

This example extends the one in [Semantic memory](../semantic-memory.md), so
that each relevant record is indexed for both kinds of search:

```python
import os

from sci_etl_core import AsyncCompositeIngestor
from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)
from sci_etl_core.search import AsyncHybridSearcher, AsyncSearchIndexer, AsyncSqliteFts5Store

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
vector_store = AsyncSqliteEmbeddingStore("memory.db")
text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))

ingestor = AsyncCompositeIngestor(
    AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=vector_store),
    AsyncSearchIndexer(store=text_store),
    logger=print,
)


async def show_matches(query: str) -> None:
    searcher = AsyncHybridSearcher(text_store, AsyncSimilarArticleFinder(embedder, vector_store))
    outcome = await searcher.search(query, top_k=10)
    if outcome.degraded:
        print(f"Degraded: {', '.join(outcome.degraded)}")
    for hit in outcome.hits:
        print(f"{hit.score:.4f}  {hit.record_id}  {hit.title}")
```

Add the ingestor to the pipeline from the
[Quick start](../../getting-started/quick-start.md):

```python
pipeline = AsyncETLPipeline(
    ...,
    logger=print,
    memory_ingestor=ingestor,
    closeables=[client, llm, embedder, vector_store, text_store],
)
```

- **Closing the stores.** `text_store` belongs in `closeables` for the same
  reason `vector_store` does, because this is a one-shot script: the pipeline
  owns both stores, so `show_matches` must run inside `async with pipeline`. A
  long-lived application follows [Store ownership](store-ownership.md) instead.
- **One log stream.** The same `logger` goes to the composite and the
  pipeline, so memory faults appear in one stream. A `SearchStoreError` while
  indexing is logged as `Memory ingest failed for <record_id> in
  AsyncSearchIndexer: ...`, and the record's chunks are still embedded and its
  entities still exported. An embedding fault likewise leaves the text index
  unaffected. A `SearchQueryError` is not a memory fault and fails the record.
- **Ingestor order.** `AsyncCompositeIngestor` returns its first ingestor's
  count, so pass the chunk ingestor first; an `AsyncSearchIndexer` in first
  place raises `ValueError`. Without embeddings, pass an `AsyncSearchIndexer`
  straight to `memory_ingestor=`.
- **What gets indexed.** One document per record, holding its title, abstract,
  full text, and `metadata`. Re-ingesting a record replaces its document, and
  a record whose title, abstract, and text are all blank is removed.

## In this section

- [Query syntax](query-syntax.md) — the Boolean query language and its parser.
- [Ranked search and filtering](ranked-search.md) — `search` versus `filter_ids`, and snippets.
- [Hybrid search](hybrid-search.md) — fusing BM25 with embedding similarity.
- [Filters and facets](filters-and-facets.md) — metadata and range filters, facet and range counts.
- [Text stores](text-stores.md) — the in-memory and SQLite FTS5 indexes.
- [Backfilling from vector memory](backfill.md) — building the text index from stored chunks.
- [Discovery graphs](discovery-graphs.md) — graphs of related papers.
- [Building a user interface](user-interfaces.md) — the read-model a UI renders.
- [Store ownership](store-ownership.md) — who closes a store, and when.
