from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.exceptions import EmbeddingError


class AsyncSentenceTransformerEmbedder(AsyncEmbedder):
    """Embed text locally with the optional ``sentence-transformers`` package.

    Runs with no network access, trading a heavier install for zero per-request
    cost. The blocking ``encode`` call is offloaded to a worker thread so the
    event loop is never stalled. A preloaded model may be injected to keep the
    hard dependency out of import-time and test paths.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", model: Any = None) -> None:
        self._model = model if model is not None else self._load(model_name)

    @staticmethod
    def _load(model_name: str) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is required for local embedding; "
                "install it or inject a preloaded model"
            ) from exc
        return SentenceTransformer(model_name)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        encoded = await asyncio.to_thread(self._encode, list(texts))
        return [[float(value) for value in vector] for vector in encoded]

    def _encode(self, texts: list[str]) -> Any:
        return self._model.encode(texts, convert_to_numpy=True)
