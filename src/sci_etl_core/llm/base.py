from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core._deprecation import is_bundled, warn_deprecated
from sci_etl_core.models import RawRecord


class LLMClient(ABC):
    """Blocking counterpart of :class:`~sci_etl_core.llm.async_base.AsyncLLMClient`.

    .. deprecated:: 0.5.0
        Subclassing it outside sci-etl-core emits a
        :class:`DeprecationWarning`. The blocking contracts will be removed in
        0.6.0; implement :class:`AsyncLLMClient` instead.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_bundled(cls):
            warn_deprecated("The blocking LLMClient contract", "implement AsyncLLMClient instead", stacklevel=3)

    @abstractmethod
    def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        """Send a chat completion request and parse the JSON response body."""


class RelevanceFilter(ABC):
    """Blocking relevance filter; wrap it in ``SyncRelevanceFilterAdapter``.

    .. deprecated:: 0.5.0
        Subclassing it outside sci-etl-core emits a
        :class:`DeprecationWarning`. The blocking contracts will be removed in
        0.6.0; implement :class:`AsyncRelevanceFilter` instead.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_bundled(cls):
            warn_deprecated(
                "The blocking RelevanceFilter contract", "implement AsyncRelevanceFilter instead", stacklevel=3
            )

    @abstractmethod
    def is_relevant(self, record: RawRecord) -> bool:
        """Decide whether a record should proceed through the pipeline."""


class EntityExtractor(ABC):
    """Blocking entity extractor; wrap it in ``SyncEntityExtractorAdapter``.

    .. deprecated:: 0.5.0
        Subclassing it outside sci-etl-core emits a
        :class:`DeprecationWarning`. The blocking contracts will be removed in
        0.6.0; implement :class:`AsyncEntityExtractor` instead.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_bundled(cls):
            warn_deprecated(
                "The blocking EntityExtractor contract", "implement AsyncEntityExtractor instead", stacklevel=3
            )

    @abstractmethod
    def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        """Extract structured entities from raw text, raising on failure."""
