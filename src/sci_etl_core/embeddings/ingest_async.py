from __future__ import annotations

from typing import Any

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.chunking import TextChunker
from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, EmbeddingChunk
from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.models import RawRecord


class AsyncChunkIngestor:
    """Chunk an article's full text, embed each passage, and add it to memory.

    Intended as the second stage after an abstract-level relevance gate: only
    articles that already cleared the gate reach here, so the cost of embedding
    a whole body is spent only on records worth remembering. It satisfies
    :class:`~sci_etl_core.ingest_protocol.MemoryIngestor`.
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
        """Replace the record's stored passages with those of ``text``.

        Every earlier chunk of the record is removed, so re-ingesting text that
        yields fewer passages leaves no stale chunks behind, and text with no
        passages clears the record from memory. Each chunk's metadata is the
        record's ``title`` and ``source_url`` only; ``record.metadata`` is not
        stored in the vector memory.

        Returns:
            The number of chunks stored.

        Raises:
            EmbeddingError: The embedder returned a different number of vectors
                than it was given passages.
            EmbeddingStoreError: The store could not be written.
        """
        passages = self._chunker.chunk(text)
        vectors = await self._embedder.embed(passages) if passages else []
        if len(vectors) != len(passages):
            raise EmbeddingError(
                f"Embedder returned {len(vectors)} vectors for {len(passages)} passages"
            )
        metadata = self._metadata_for(record)
        items = [
            EmbeddingChunk(record.record_id, index, passage, vector, dict(metadata))
            for index, (passage, vector) in enumerate(zip(passages, vectors, strict=True))
        ]
        await self._store.replace_record(record.record_id, items)
        return len(items)

    @staticmethod
    def _metadata_for(record: RawRecord) -> dict[str, Any]:
        return {"title": record.title, "source_url": record.source_url}
