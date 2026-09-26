from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core.models import TokenUsage


class AsyncLLMClient(ABC):
    """Contract for a chat-completion backend that answers with a JSON object.

    The relevance filter and the entity extractor depend only on this
    interface, so a provider, a cache such as
    :class:`~sci_etl_core.llm.cache_async.CachingLLMClient`, or a test double
    can be injected in its place.
    """

    @abstractmethod
    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:  # noqa: ASYNC109
        """Send a chat completion request and return the parsed JSON object.

        Raises:
            LLMError: The request failed, or the body is not a JSON object.
        """

    async def invalidate(self, system_prompt: str, user_content: str) -> None:  # noqa: B027
        """Report that the response to this request was rejected as unusable.

        :class:`~sci_etl_core.llm.cache_async.CachingLLMClient` removes the
        cached response, so the next request reaches the LLM again. A client
        that keeps no responses does nothing, which is the default.
        """

    @property
    def response_format(self) -> dict[str, Any]:
        """The ``response_format`` requested with each completion, ``{"type": "json_object"}`` by default.

        A subclass that requests another format overrides this property.
        :class:`~sci_etl_core.llm.cache_async.CachingLLMClient` keys its cache
        on the value, so answers requested in different formats never share a
        cache entry.
        """
        return {"type": "json_object"}

    @property
    def usage(self) -> TokenUsage | None:
        """Tokens this client has used so far, or ``None`` when it does not track usage."""
        return None
