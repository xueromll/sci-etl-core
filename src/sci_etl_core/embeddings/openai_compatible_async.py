from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from pydantic import SecretStr

from sci_etl_core._retry_after import retry_after_from_error, retry_delay
from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.llm._utils import reveal_secret
from sci_etl_core.models import TokenUsage

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
        max_retry_after: float = 60.0,
    ) -> None:
        """Configure the embedder.

        This embedder is the only retry layer: the OpenAI SDK's own retries are
        turned off, so ``max_retries`` is the total number of attempts per
        batch. Between attempts it waits ``backoff_factor ** attempt`` seconds,
        or longer when the server's ``retry-after-ms`` or ``Retry-After`` header
        asks for it, up to ``max_retry_after`` seconds.

        Raises:
            ValueError: ``max_retries`` is less than 1, which would fail every
                request without making a single attempt, or
                ``max_retry_after`` is negative.
        """
        if max_retries < 1:
            raise ValueError("max_retries must be a positive integer")
        if max_retry_after < 0:
            raise ValueError("max_retry_after must not be negative")
        self._client = AsyncOpenAI(api_key=reveal_secret(api_key), base_url=base_url, max_retries=0)
        self._model = model
        self._batch_size = max(1, batch_size)
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._sleep = sleep
        self._max_retry_after = max_retry_after
        self._usage = TokenUsage()

    @property
    def usage(self) -> TokenUsage:
        """Tokens reported across every response received so far, as a snapshot."""
        return replace(self._usage)

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
                self._usage.record(getattr(response, "usage", None))
                return [list(item.embedding) for item in response.data]
            except _RETRYABLE as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    await self._sleep(
                        retry_delay(attempt, self._backoff_factor, retry_after_from_error(exc), self._max_retry_after)
                    )
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
