from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.models import RawRecord

_AFFIRMATIVE = frozenset({"true", "yes", "1"})
_NEGATIVE = frozenset({"false", "no", "0"})


def _read_verdict(result: Any) -> bool | None:
    """Interpret the ``relevant`` value, or return ``None`` when it is not a clear verdict."""
    if not isinstance(result, dict):
        return None
    value = result.get("relevant")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        word = value.strip().casefold()
        if word in _AFFIRMATIVE:
            return True
        if word in _NEGATIVE:
            return False
    return None


class AsyncRelevanceFilter(ABC):
    @abstractmethod
    async def is_relevant(self, record: RawRecord) -> bool:
        """Decide whether a record should proceed through the pipeline."""


class AsyncLLMRelevanceFilter(AsyncRelevanceFilter):
    def __init__(
        self,
        llm_client: AsyncLLMClient,
        system_prompt: str,
        timeout: int = 20,
        default_on_empty_abstract: bool = True,
        default_on_error: bool = True,
    ) -> None:
        self._llm_client = llm_client
        self._system_prompt = system_prompt
        self._timeout = timeout
        self._default_on_empty_abstract = default_on_empty_abstract
        self._default_on_error = default_on_error

    async def is_relevant(self, record: RawRecord) -> bool:
        """Ask the LLM for a verdict read from the ``relevant`` key.

        A boolean is used as-is; ``0``/``1`` and the strings ``"true"``,
        ``"false"``, ``"yes"``, ``"no"``, ``"1"`` and ``"0"`` (any case) are
        accepted too. A failed call, a response that is not a JSON object, and a
        missing or unrecognized verdict all return ``default_on_error``, so a
        garbled answer such as the string ``"false"`` read as truthy can never
        pass for a confident verdict.
        """
        if not record.abstract:
            return self._default_on_empty_abstract
        try:
            content = f"Title: {record.title}\nAbstract: {record.abstract}"
            result = await self._llm_client.complete_json(self._system_prompt, content, self._timeout)
        except asyncio.CancelledError:
            raise
        except LLMError:
            return self._default_on_error
        verdict = _read_verdict(result)
        return self._default_on_error if verdict is None else verdict
