from __future__ import annotations

from typing import Any

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.chunking import TextChunker
from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, EmbeddingChunk
from sci_etl_core.models import RawRecord


class AsyncChunkIngestor:
    """Chunk an article's full text, embed each passage, and add it to memory.

    Intended as the second stage after an abstract-level relevance gate: only
    articles that already cleared the gate reach here, so the cost of embedding
    a whole body is spent only on records worth remembering.
    """

    def __init__(
        self,
        chunker: TextChunker,
        embedder: AsyncEmbedder,
        store: AsyncEmbeddingStore,
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder
        self._store = store

    async def ingest(self, record: RawRecord, text: str) -> int:
        passages = self._chunker.chunk(text)
        if not passages:
            return 0
        vectors = await self._embedder.embed(passages)
        metadata = self._metadata_for(record)
        items = [
            EmbeddingChunk(record.record_id, index, passage, vector, dict(metadata))
            for index, (passage, vector) in enumerate(zip(passages, vectors))
        ]
        await self._store.add(items)
        return len(items)

    @staticmethod
    def _metadata_for(record: RawRecord) -> dict[str, Any]:
        return {"title": record.title, "source_url": record.source_url}
