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
    """Contract for the gate that decides, from a listing entry alone, whether a record is worth its full text."""

    @abstractmethod
    async def is_relevant(self, record: RawRecord) -> bool:
        """Decide whether a record should proceed through the pipeline."""


class AsyncLLMRelevanceFilter(AsyncRelevanceFilter):
    """Ask an LLM whether a record's title and abstract match ``system_prompt``."""

    def __init__(
        self,
        llm_client: AsyncLLMClient,
        system_prompt: str,
        timeout: int = 20,
        default_on_empty_abstract: bool = True,
        default_on_error: bool = True,
    ) -> None:
        """Configure the filter.

        ``system_prompt`` must ask for a JSON object with a ``relevant`` key.
        ``timeout`` is passed to every completion. A record without an abstract
        is not sent and reads as ``default_on_empty_abstract``, which defaults
        to ``True``.

        ``default_on_error`` decides what an
        :class:`~sci_etl_core.exceptions.LLMError` or an unclear verdict does.
        ``True``, the default, lets the record through, so a fault costs an
        extraction call rather than a record. ``False`` fails closed: the fault
        raises, the record is neither extracted nor marked processed, and the
        pipeline counts a failed attempt and retries it on the next run. A
        fault never reads as a verdict of irrelevance, since that would mark the
        record processed for good.
        """
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
        missing or unrecognized verdict all count as a fault, so a garbled
        answer such as the string ``"false"`` read as truthy can never pass for
        a confident verdict. A fault returns ``True`` when ``default_on_error``
        is ``True`` and raises otherwise. A response without a clear verdict is
        reported through
        :meth:`~sci_etl_core.llm.async_base.AsyncLLMClient.invalidate`, so a
        caching client does not replay it.

        Raises:
            LLMError: ``default_on_error`` is ``False`` and the call failed or
                gave no clear verdict.
        """
        if not record.abstract:
            return self._default_on_empty_abstract
        content = f"Title: {record.title}\nAbstract: {record.abstract}"
        try:
            result = await self._llm_client.complete_json(self._system_prompt, content, self._timeout)
        except asyncio.CancelledError:
            raise
        except LLMError:
            if self._default_on_error:
                return True
            raise
        verdict = _read_verdict(result)
        if verdict is not None:
            return verdict
        await self._llm_client.invalidate(self._system_prompt, content)
        if self._default_on_error:
            return True
        raise LLMError("LLM response holds no clear relevance verdict")
