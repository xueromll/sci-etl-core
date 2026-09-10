from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
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


class AsyncEmbeddingStore(ABC):
    """An accumulating vector memory of article chunks, searchable by meaning."""

    @abstractmethod
    async def add(self, chunks: Sequence[EmbeddingChunk]) -> None:
        """Persist chunk embeddings, replacing any with the same id and index."""

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
        compared against every other article without matching itself.
        """

    @abstractmethod
    async def count(self) -> int:
        """Return the number of stored chunks."""

    async def aclose(self) -> None:
        """Release any held resources. No-op by default."""
        return None
