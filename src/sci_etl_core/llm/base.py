from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    @abstractmethod
    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        """Send a chat completion request and parse the JSON response body."""
