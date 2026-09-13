from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "LLMClient": "sci_etl_core.llm.base",
    "RelevanceFilter": "sci_etl_core.llm.base",
    "EntityExtractor": "sci_etl_core.llm.base",
    "SyncLLMClientAdapter": "sci_etl_core.llm._adapters",
    "AsyncLLMClient": "sci_etl_core.llm.async_base",
    "AsyncOpenAICompatibleClient": "sci_etl_core.llm.openai_compatible_async",
    "AsyncEntityExtractor": "sci_etl_core.llm.extraction_async",
    "AsyncLLMEntityExtractor": "sci_etl_core.llm.extraction_async",
    "AsyncRelevanceFilter": "sci_etl_core.llm.relevance_async",
    "AsyncLLMRelevanceFilter": "sci_etl_core.llm.relevance_async",
    "AsyncEmbeddingRelevanceFilter": "sci_etl_core.llm.relevance_embedding_async",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.llm.base import LLMClient
    from sci_etl_core.llm.base import RelevanceFilter
    from sci_etl_core.llm.base import EntityExtractor
    from sci_etl_core.llm._adapters import SyncLLMClientAdapter
    from sci_etl_core.llm.async_base import AsyncLLMClient
    from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient
    from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
    from sci_etl_core.llm.extraction_async import AsyncLLMEntityExtractor
    from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
    from sci_etl_core.llm.relevance_async import AsyncLLMRelevanceFilter
    from sci_etl_core.llm.relevance_embedding_async import AsyncEmbeddingRelevanceFilter
