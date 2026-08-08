from __future__ import annotations

import asyncio
import json
from typing import Any

from openai import AsyncOpenAI
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from pydantic import SecretStr

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm.async_base import AsyncLLMClient

_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


def _reveal(api_key: str | SecretStr) -> str:
    return api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key


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
    ) -> None:
        self._client = AsyncOpenAI(api_key=_reveal(api_key), base_url=base_url)
        self._model = model
        self._default_timeout = default_timeout
        self._temperature = temperature
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._sleep = sleep

    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
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
                return self._parse(response)
            except _RETRYABLE as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    await self._sleep(self._backoff_factor ** attempt)
            except LLMError:
                raise
            except json.JSONDecodeError as exc:
                raise LLMError(f"LLM returned malformed JSON: {exc}") from exc
            except Exception as exc:
                raise LLMError(f"LLM completion failed: {exc}") from exc
        raise LLMError(f"LLM completion failed after {self._max_retries} attempts: {last_error}")

    @staticmethod
    def _parse(response: Any) -> dict[str, Any]:
        if not response.choices:
            raise LLMError("LLM response contained no choices")
        content = response.choices[0].message.content
        if not content:
            return {}
        return json.loads(content.strip())
