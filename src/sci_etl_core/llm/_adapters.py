from __future__ import annotations

import asyncio
from typing import Any

from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.base import LLMClient

__all__ = ["SyncLLMClientAdapter"]


class SyncLLMClientAdapter(AsyncLLMClient):
    """Expose a synchronous LLM client through the async client contract."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    async def complete_json(
        self, system_prompt: str, user_content: str, timeout: int | None = None
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._llm_client.complete_json, system_prompt, user_content, timeout
        )
