from __future__ import annotations

from abc import ABC, abstractmethod

from sci_etl_core.llm.base import LLMClient
from sci_etl_core.models import RawRecord


class RelevanceFilter(ABC):
    @abstractmethod
    async def is_relevant(self, record: RawRecord) -> bool:
        """Decide whether a record deserves full-text extraction."""


class LLMRelevanceFilter(RelevanceFilter):
    def __init__(
        self,
        llm_client: LLMClient,
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
        if not record.abstract:
            return self._default_on_empty_abstract
        try:
            content = f"Title: {record.title}\nAbstract: {record.abstract}"
            result = await self._llm_client.complete_json(self._system_prompt, content, self._timeout)
            return bool(result.get("relevant", False))
        except Exception:
            return self._default_on_error
