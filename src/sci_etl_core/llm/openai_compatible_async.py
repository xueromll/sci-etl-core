from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError
from pydantic import SecretStr

from sci_etl_core._retry_after import retry_after_from_error, retry_delay
from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm._utils import reveal_secret
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.models import TokenUsage
from sci_etl_core.rate_limiter import RateLimiting, limiter_for

if TYPE_CHECKING:
    from sci_etl_core.config import LLMConfig

_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


class AsyncOpenAICompatibleClient(AsyncLLMClient):
    def __init__(
        self,
        api_key: str | SecretStr,
        base_url: str,
        model: str,
        default_timeout: int = 120,
        temperature: float = 0.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        sleep: Any = asyncio.sleep,
        max_retry_after: float = 60.0,
        rate_limiter: RateLimiting | None = None,
    ) -> None:
        """Configure the client.

        This client is the only retry layer: the OpenAI SDK's own retries are
        turned off, so ``max_retries`` is the total number of attempts. Between
        attempts it waits ``backoff_factor ** attempt`` seconds, or longer when
        the server's ``retry-after-ms`` or ``Retry-After`` header asks for it,
        up to ``max_retry_after`` seconds.

        Every attempt first enters ``rate_limiter``, an
        :class:`~sci_etl_core.rate_limiter.AsyncRateLimiter` or a
        :class:`~sci_etl_core.rate_limiter.HostRateLimiter` matched against
        ``base_url``, and releases it once the response arrives. Share one
        limiter between a chat client and an embedder that call the same
        provider to keep both inside one budget.

        Raises:
            ValueError: ``max_retries`` is less than 1, which would fail every
                completion without making a single attempt, or
                ``max_retry_after`` is negative.
        """
        if max_retries < 1:
            raise ValueError("max_retries must be a positive integer")
        if max_retry_after < 0:
            raise ValueError("max_retry_after must not be negative")
        self._client = AsyncOpenAI(api_key=reveal_secret(api_key), base_url=base_url, max_retries=0)
        self._model = model
        self._default_timeout = default_timeout
        self._temperature = temperature
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._sleep = sleep
        self._max_retry_after = max_retry_after
        self._usage = TokenUsage()
        self._base_url = base_url
        self._rate_limiter = rate_limiter

    @classmethod
    def from_config(cls, llm: LLMConfig, **options: Any) -> "AsyncOpenAICompatibleClient":
        """Build a client from the ``llm`` config section.

        The section supplies ``api_key``, ``base_url``, ``model``, and
        ``timeout`` as ``default_timeout``. ``options`` pass any other
        constructor argument, such as ``rate_limiter``, and override a value
        taken from the config.
        """
        settings: dict[str, Any] = {
            "api_key": llm.api_key,
            "base_url": llm.base_url,
            "model": llm.model,
            "default_timeout": llm.timeout,
        }
        settings.update(options)
        return cls(**settings)

    @property
    def model(self) -> str:
        """The model completions are requested from."""
        return self._model

    @property
    def usage(self) -> TokenUsage:
        """Tokens reported across every response received so far, as a snapshot."""
        return replace(self._usage)

    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        """Request a JSON-mode completion and return the parsed object.

        An empty completion reads as ``{}``. Every response the API returns
        counts toward :attr:`usage`, including one whose body is then rejected.

        Raises:
            LLMError: The request failed after retries, or the completion is
                not valid JSON or is JSON other than an object.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                async with limiter_for(self._rate_limiter, self._base_url):
                    response = await self._client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=self._temperature,
                        response_format={"type": "json_object"},
                        timeout=timeout or self._default_timeout,
                    )
                self._usage.record(getattr(response, "usage", None))
                return self._parse(response)
            except _RETRYABLE as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    await self._sleep(
                        retry_delay(attempt, self._backoff_factor, retry_after_from_error(exc), self._max_retry_after)
                    )
            except LLMError:
                raise
            except json.JSONDecodeError as exc:
                raise LLMError(f"LLM returned malformed JSON: {exc}") from exc
            except Exception as exc:
                raise LLMError(f"LLM completion failed: {exc}") from exc
        raise LLMError(f"LLM completion failed after {self._max_retries} attempts: {last_error}")

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.close()

    @staticmethod
    def _parse(response: Any) -> dict[str, Any]:
        if not response.choices:
            raise LLMError("LLM response contained no choices")
        content = response.choices[0].message.content
        if not content:
            return {}
        parsed = json.loads(content.strip())
        if not isinstance(parsed, dict):
            raise LLMError(f"LLM returned JSON {type(parsed).__name__}, not an object")
        return parsed
