from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from pydantic import SecretStr

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.llm._utils import reveal_secret

_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


class AsyncOpenAIEmbedder(AsyncEmbedder):
    """Embed text through any OpenAI-compatible ``/embeddings`` endpoint."""

    def __init__(
        self,
        api_key: str | SecretStr,
        base_url: str,
        model: str,
        batch_size: int = 128,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        sleep: Any = asyncio.sleep,
    ) -> None:
        """Configure the embedder.

        Raises:
            ValueError: ``max_retries`` is less than 1, which would fail every
                request without making a single attempt.
        """
        if max_retries < 1:
            raise ValueError("max_retries must be a positive integer")
        self._client = AsyncOpenAI(api_key=reveal_secret(api_key), base_url=base_url)
        self._model = model
        self._batch_size = max(1, batch_size)
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._sleep = sleep

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.embeddings.create(model=self._model, input=batch)
                return [list(item.embedding) for item in response.data]
            except _RETRYABLE as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    await self._sleep(self._backoff_factor ** attempt)
            except asyncio.CancelledError:
                raise
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError(f"Embedding request failed: {exc}") from exc
        raise EmbeddingError(
            f"Embedding request failed after {self._max_retries} attempts: {last_error}"
        )

    async def aclose(self) -> None:
        await self._client.close()
