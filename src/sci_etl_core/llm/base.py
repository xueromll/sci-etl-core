from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core.models import RawRecord


class LLMClient(ABC):
    """Blocking counterpart of :class:`~sci_etl_core.llm.async_base.AsyncLLMClient`."""

    @abstractmethod
    def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        """Send a chat completion request and parse the JSON response body."""


class RelevanceFilter(ABC):
    """Blocking relevance filter; wrap it in ``SyncRelevanceFilterAdapter``."""

    @abstractmethod
    def is_relevant(self, record: RawRecord) -> bool:
        """Decide whether a record should proceed through the pipeline."""


class EntityExtractor(ABC):
    """Blocking entity extractor; wrap it in ``SyncEntityExtractorAdapter``."""

    @abstractmethod
    def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        """Extract structured entities from raw text, raising on failure."""
