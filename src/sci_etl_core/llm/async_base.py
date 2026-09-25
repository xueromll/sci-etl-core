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

    @property
    def usage(self) -> TokenUsage | None:
        """Tokens this client has used so far, or ``None`` when it does not track usage."""
        return None
