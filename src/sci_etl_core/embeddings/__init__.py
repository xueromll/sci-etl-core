from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "AsyncEmbedder": "sci_etl_core.embeddings.async_base",
    "AsyncOpenAIEmbedder": "sci_etl_core.embeddings.openai_compatible_async",
    "AsyncSentenceTransformerEmbedder": "sci_etl_core.embeddings.sentence_transformer_async",
    "TextChunker": "sci_etl_core.embeddings.chunking",
    "SlidingWindowChunker": "sci_etl_core.embeddings.chunking",
    "AsyncEmbeddingStore": "sci_etl_core.embeddings.store_base",
    "EmbeddingChunk": "sci_etl_core.embeddings.store_base",
    "SearchHit": "sci_etl_core.embeddings.store_base",
    "StoredRecord": "sci_etl_core.embeddings.store_base",
    "InMemoryEmbeddingStore": "sci_etl_core.embeddings.store_memory",
    "AsyncSqliteEmbeddingStore": "sci_etl_core.embeddings.store_sqlite_async",
    "AsyncChunkIngestor": "sci_etl_core.embeddings.ingest_async",
    "AsyncSimilarArticleFinder": "sci_etl_core.embeddings.finder_async",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.embeddings.async_base import AsyncEmbedder
    from sci_etl_core.embeddings.chunking import SlidingWindowChunker, TextChunker
    from sci_etl_core.embeddings.finder_async import AsyncSimilarArticleFinder
    from sci_etl_core.embeddings.ingest_async import AsyncChunkIngestor
    from sci_etl_core.embeddings.openai_compatible_async import AsyncOpenAIEmbedder
    from sci_etl_core.embeddings.sentence_transformer_async import AsyncSentenceTransformerEmbedder
    from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, EmbeddingChunk, SearchHit, StoredRecord
    from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
    from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
