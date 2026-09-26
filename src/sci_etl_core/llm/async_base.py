from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
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

    async def complete_structured(
        self,
        system_prompt: str,
        user_content: str,
        schema: Mapping[str, Any],
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> dict[str, Any]:
        """Request a JSON object that should match the JSON Schema ``schema``.

        A provider that supports JSON-schema structured output is asked for
        it. The default calls :meth:`complete_json`, so the answer comes in
        JSON mode and the caller validates it against ``schema`` itself;
        :class:`~sci_etl_core.llm.extraction_async.AsyncLLMEntityExtractor`
        always does.

        Raises:
            LLMError: The request failed, or the body is not a JSON object.
        """
        return await self.complete_json(system_prompt, user_content, timeout)

    async def invalidate(  # noqa: B027
        self, system_prompt: str, user_content: str, *, schema: Mapping[str, Any] | None = None
    ) -> None:
        """Report that the response to this request was rejected as unusable.

        ``schema`` is the one passed to :meth:`complete_structured`, or
        ``None`` for a :meth:`complete_json` request.
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
