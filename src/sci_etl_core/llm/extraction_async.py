from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm._chunking import truncate_to_tokens
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.html import HtmlTextParser


class AsyncEntityExtractor(ABC):
    @abstractmethod
    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        """Extract structured entities from raw text."""


class AsyncLLMEntityExtractor(AsyncEntityExtractor):
    def __init__(
        self,
        llm_client: AsyncLLMClient,
        system_prompt: str,
        html_parser: Parser | None = None,
        result_key: str = "items",
        max_chars: int = 120_000,
        timeout: int = 120,
        max_tokens: int | None = None,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self._llm_client = llm_client
        self._system_prompt = system_prompt
        self._html_parser = html_parser or HtmlTextParser()
        self._result_key = result_key
        self._max_chars = max_chars
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._encoding_name = encoding_name

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        cleaned = text.decode("utf-8", errors="ignore") if isinstance(text, bytes) else text
        if cleaned[:200].lstrip().startswith("<"):
            cleaned = self._html_parser.extract_text(cleaned.encode("utf-8"))
        cleaned = self._truncate(cleaned)

        try:
            result = await self._llm_client.complete_json(self._system_prompt, cleaned, self._timeout)
        except asyncio.CancelledError:
            raise
        except LLMError:
            return []

        if self._result_key in result:
            return list(result[self._result_key])
        if len(result) == 1:
            return list(next(iter(result.values())))
        return []

    def _truncate(self, text: str) -> str:
        """Truncate by token count when configured, else by character count.

        Token-aware truncation requires ``tiktoken``; when it is absent the
        character cap (``max_chars``) is used instead.
        """
        if self._max_tokens is not None:
            truncated = truncate_to_tokens(text, self._max_tokens, self._encoding_name)
            if truncated is not None:
                return truncated
        return text[: self._max_chars]
