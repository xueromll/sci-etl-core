from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core.models import TokenUsage


class AsyncLLMClient(ABC):
    @abstractmethod
    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        """Send a chat completion request and return the parsed JSON object.

        Raises:
            LLMError: The request failed, or the body is not a JSON object.
        """

    @property
    def usage(self) -> TokenUsage | None:
        """Tokens this client has used so far, or ``None`` when it does not track usage."""
        return None
