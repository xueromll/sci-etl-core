from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EmbeddingChunk:
    """A single passage of an article, paired with its embedding vector."""

    record_id: str
    chunk_index: int
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchHit:
    """A stored chunk returned from a similarity query, with its score."""

    record_id: str
    chunk_index: int
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """The passages a vector memory holds for one record, without their vectors.

    ``passages`` are the chunk texts in ``chunk_index`` order, and ``metadata``
    is the metadata of the record's first chunk, which for chunks stored by
    :class:`~sci_etl_core.embeddings.ingest_async.AsyncChunkIngestor` holds the
    record's ``title`` and ``source_url``.
    """

    record_id: str
    passages: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class AsyncEmbeddingStore(ABC):
    """An accumulating vector memory of article chunks, searchable by meaning."""

    @abstractmethod
    async def add(self, chunks: Sequence[EmbeddingChunk]) -> None:
        """Persist chunk embeddings, replacing any with the same id and index."""

    @abstractmethod
    async def delete_record(self, record_id: str) -> None:
        """Remove every stored chunk belonging to ``record_id``."""

    async def replace_record(self, record_id: str, chunks: Sequence[EmbeddingChunk]) -> None:
        """Make ``chunks`` the only stored chunks of ``record_id``.

        Adding alone would leave a record's old higher-index chunks behind when
        its text now yields fewer passages. The default deletes and then adds;
        a backend that can do both atomically should override it.
        """
        await self.delete_record(record_id)
        await self.add(chunks)

    @abstractmethod
    async def query(
        self,
        vector: Sequence[float],
        top_k: int = 5,
        min_score: float = -1.0,
        exclude_record_id: str | None = None,
    ) -> list[SearchHit]:
        """Return the nearest stored chunks to ``vector`` by cosine similarity.

        ``exclude_record_id`` drops a record's own chunks, so an article can be
        compared against every other article without matching itself. A stored
        vector whose score is not finite, such as one holding NaN, never matches.
        """

    @abstractmethod
    async def count(self) -> int:
        """Return the number of stored chunks."""

    def iter_records(self, batch_size: int = 100) -> AsyncIterator[StoredRecord]:
        """Yield every stored record's passages, in ``record_id`` order, without loading vectors.

        ``batch_size`` is how many records are read at a time. A backend that
        cannot enumerate its chunks keeps this default, which raises; the
        bundled stores implement it.

        Raises:
            NotImplementedError: The store cannot enumerate its records.
        """
        raise NotImplementedError(f"{type(self).__name__} cannot enumerate its stored records")

    async def aclose(self) -> None:
        """Release any held resources. No-op by default."""
        return None
