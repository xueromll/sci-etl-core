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
            query = vectors[0] if vectors else []
            return top_similarity(query, references) >= self._threshold
        except asyncio.CancelledError:
            raise
        except EmbeddingError:
            return self._default_on_error

    async def _ensure_references(self) -> np.ndarray:
        if self._reference_matrix is None:
            async with self._lock:
                if self._reference_matrix is None:
                    vectors = await self._embedder.embed(self._reference_texts)
                    self._reference_matrix = l2_normalize(to_matrix(vectors))
        return self._reference_matrix
