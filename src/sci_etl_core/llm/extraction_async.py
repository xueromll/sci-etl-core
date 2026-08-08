from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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
    ) -> None:
        self._llm_client = llm_client
        self._system_prompt = system_prompt
        self._html_parser = html_parser or HtmlTextParser()
        self._result_key = result_key
        self._max_chars = max_chars
        self._timeout = timeout

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        cleaned = text.decode("utf-8", errors="ignore") if isinstance(text, bytes) else text
        if cleaned[:200].lstrip().startswith("<"):
            cleaned = self._html_parser.extract_text(cleaned.encode("utf-8"))
        cleaned = cleaned[: self._max_chars]

        try:
            result = await self._llm_client.complete_json(self._system_prompt, cleaned, self._timeout)
        except Exception:
            return []

        if self._result_key in result:
            return list(result[self._result_key])
        if len(result) == 1:
            return list(next(iter(result.values())))
        return []
