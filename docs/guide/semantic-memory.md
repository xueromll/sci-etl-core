# Semantic memory

Semantic memory is optional and needs the `embeddings` extra. Pass a
`memory_ingestor` to chunk and embed each relevant record's full text into a
vector store. You can then search that store by meaning:

```python
import os

from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
store = AsyncSqliteEmbeddingStore("memory.db")
ingestor = AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=store)


async def show_similar(text: str) -> None:
    finder = AsyncSimilarArticleFinder(embedder, store)
    for record_id, score, metadata in await finder.find_similar_articles(text, top_k=5):
        print(f"{score:.2f}  {record_id}  {metadata['title']}")
```

Add the ingestor to the pipeline from the [Quick start](../getting-started/quick-start.md),
and list the embedder and store among its closeables:

```python
pipeline = AsyncETLPipeline(..., memory_ingestor=ingestor, closeables=[client, embedder, store])
```

- **What gets stored.** Ingestion runs after the relevance gate, so only
  relevant records are embedded. `SlidingWindowChunker` defaults to 350-word
  windows with a 50-word overlap. Re-ingesting a record replaces all of its
  chunks, so text that now yields fewer passages leaves nothing stale behind.
- **Failures.** An `EmbeddingError` or `EmbeddingStoreError` during ingestion
  is logged, and the record's entities are still exported. That includes a
  memory file that isn't a SQLite database, and an embedder that returns a
  different number of vectors than passages.
- **Stores.** `InMemoryEmbeddingStore()` suits tests and short-lived runs.
  `AsyncSqliteEmbeddingStore` persists vectors with the standard-library
  `sqlite3` module and scans every stored vector on each query. It serializes
  access to its connection, so concurrent records can share one store, and
  each write is a single transaction. A stored vector holding NaN or infinity
  never appears in results.
- **Custom stores.** Subclasses of `AsyncEmbeddingStore` implement `add`,
  `delete_record`, `query`, and `count`. `replace_record` defaults to delete
  then add; override it if your backend can do both atomically.
- **Local embeddings.** `AsyncSentenceTransformerEmbedder("all-MiniLM-L6-v2")`
  embeds without network calls. It needs the `embeddings-local` extra, loads
  the model when constructed, and accepts a preloaded `model=`.

## Relevance without an LLM

`AsyncEmbeddingRelevanceFilter` keeps a record when its title and abstract are
close enough to any reference text:

```python
from sci_etl_core import AsyncEmbeddingRelevanceFilter

relevance_filter = AsyncEmbeddingRelevanceFilter(
    embedder=embedder,
    reference_texts=["ultra-diffuse galaxies", "low surface brightness galaxies"],
    threshold=0.35,  # minimum cosine similarity
)
```

## Searching by keyword too

To index the same records for Boolean search as well, see
[Local search and discovery](search/index.md). Its SQLite text index,
`AsyncSqliteFts5Store`, is one more store to list in `closeables` beside the
embedding store, and its `search` extra installs nothing.
