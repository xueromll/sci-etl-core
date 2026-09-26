from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "AsyncLLMClient": "sci_etl_core.llm.async_base",
    "AsyncOpenAICompatibleClient": "sci_etl_core.llm.openai_compatible_async",
    "AsyncEntityExtractor": "sci_etl_core.llm.extraction_async",
    "AsyncLLMEntityExtractor": "sci_etl_core.llm.extraction_async",
    "entity_list_schema": "sci_etl_core.llm.extraction_async",
    "AsyncRelevanceFilter": "sci_etl_core.llm.relevance_async",
    "AsyncLLMRelevanceFilter": "sci_etl_core.llm.relevance_async",
    "AsyncEmbeddingRelevanceFilter": "sci_etl_core.llm.relevance_embedding_async",
    "AsyncLLMResponseCache": "sci_etl_core.llm.cache_async",
    "AsyncSqliteLLMResponseCache": "sci_etl_core.llm.cache_async",
    "CacheStats": "sci_etl_core.llm.cache_async",
    "CachingLLMClient": "sci_etl_core.llm.cache_async",
    "InMemoryLLMResponseCache": "sci_etl_core.llm.cache_async",
    "response_cache_key": "sci_etl_core.llm.cache_async",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.llm.async_base import AsyncLLMClient
    from sci_etl_core.llm.cache_async import (
        AsyncLLMResponseCache,
        AsyncSqliteLLMResponseCache,
        CacheStats,
        CachingLLMClient,
        InMemoryLLMResponseCache,
        response_cache_key,
    )
    from sci_etl_core.llm.extraction_async import AsyncEntityExtractor, AsyncLLMEntityExtractor, entity_list_schema
    from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient
    from sci_etl_core.llm.relevance_async import AsyncLLMRelevanceFilter, AsyncRelevanceFilter
    from sci_etl_core.llm.relevance_embedding_async import AsyncEmbeddingRelevanceFilter
