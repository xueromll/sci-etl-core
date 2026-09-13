from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

import numpy as np

from sci_etl_core.embeddings._similarity import l2_normalize, to_matrix, top_similarity
from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import RawRecord


def _default_record_text(record: RawRecord) -> str:
    return f"{record.title}\n{record.abstract}".strip()


class AsyncEmbeddingRelevanceFilter(AsyncRelevanceFilter):
    """Keep records whose meaning is close to a set of reference concepts.

    Reference concepts are embedded once, lazily, on first use. Each record is
    then embedded and kept when its cosine similarity to the nearest reference
    reaches ``threshold``, so semantically related work is matched even when it
    shares no keywords with the query.

    Only a real similarity score can reject a record. A failed embedding call,
    a record vector that is missing, all zero or non-finite, and a vector whose
    dimension differs from the references all return ``default_on_error``:
    none of them is evidence that the record is irrelevant, and a negative
    verdict would mark it processed for good.
    """

    def __init__(
        self,
        embedder: AsyncEmbedder,
        reference_texts: Sequence[str],
        threshold: float = 0.35,
        record_to_text: Callable[[RawRecord], str] = _default_record_text,
        default_on_empty_abstract: bool = True,
        default_on_error: bool = True,
    ) -> None:
        if not reference_texts:
            raise ValueError("reference_texts must contain at least one concept")
        self._embedder = embedder
        self._reference_texts = list(reference_texts)
        self._threshold = threshold
        self._record_to_text = record_to_text
        self._default_on_empty_abstract = default_on_empty_abstract
        self._default_on_error = default_on_error
        self._reference_matrix: np.ndarray | None = None
        self._lock = asyncio.Lock()

    async def is_relevant(self, record: RawRecord) -> bool:
        if not record.abstract:
            return self._default_on_empty_abstract
        try:
            references = await self._ensure_references()
            vectors = await self._embedder.embed([self._record_to_text(record)])
            query = self._validated_query(vectors, references)
        except asyncio.CancelledError:
            raise
        except EmbeddingError:
            return self._default_on_error
        return top_similarity(query, references) >= self._threshold

    async def _ensure_references(self) -> np.ndarray:
        if self._reference_matrix is None:
            async with self._lock:
                if self._reference_matrix is None:
                    vectors = await self._embedder.embed(self._reference_texts)
                    try:
                        matrix = to_matrix(vectors)
                    except ValueError as exc:
                        raise EmbeddingError("Reference vectors have inconsistent dimensions") from exc
                    self._reference_matrix = l2_normalize(matrix)
        return self._reference_matrix

    @staticmethod
    def _validated_query(vectors: list[list[float]], references: np.ndarray) -> list[float]:
        if len(vectors) != 1:
            raise EmbeddingError(f"Expected one record vector, got {len(vectors)}")
        query = np.asarray(vectors[0], dtype=np.float64)
        if query.ndim != 1 or references.ndim != 2 or query.shape[0] != references.shape[1]:
            raise EmbeddingError("Record vector dimension does not match the reference vectors")
        if not np.all(np.isfinite(query)) or not np.any(query):
            raise EmbeddingError("Record vector is all zero or holds a non-finite value")
        return list(vectors[0])
