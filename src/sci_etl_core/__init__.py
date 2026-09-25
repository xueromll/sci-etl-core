"""Reusable, domain-agnostic ETL building blocks for scientific text mining.

Public names load on first access, so importing the package never requires an
optional dependency that the components you use don't need.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "SyncEntityExtractorAdapter": "sci_etl_core._adapters",
    "SyncExporterAdapter": "sci_etl_core._adapters",
    "SyncExtractorAdapter": "sci_etl_core._adapters",
    "SyncRelevanceFilterAdapter": "sci_etl_core._adapters",
    "SyncStateManagerAdapter": "sci_etl_core._adapters",
    "BaseAppConfig": "sci_etl_core.config",
    "HttpConfig": "sci_etl_core.config",
    "LLMConfig": "sci_etl_core.config",
    "PipelineConfig": "sci_etl_core.config",
    "RateLimitConfig": "sci_etl_core.config",
    "SearchConfig": "sci_etl_core.config",
    "load_config": "sci_etl_core.config",
    "load_config_async": "sci_etl_core.config_async",
    "DiscoveryResult": "sci_etl_core.discovery",
    "Facet": "sci_etl_core.discovery",
    "AsyncEmbedder": "sci_etl_core.embeddings.async_base",
    "SlidingWindowChunker": "sci_etl_core.embeddings.chunking",
    "TextChunker": "sci_etl_core.embeddings.chunking",
    "AsyncSimilarArticleFinder": "sci_etl_core.embeddings.finder_async",
    "AsyncChunkIngestor": "sci_etl_core.embeddings.ingest_async",
    "AsyncOpenAIEmbedder": "sci_etl_core.embeddings.openai_compatible_async",
    "AsyncSentenceTransformerEmbedder": "sci_etl_core.embeddings.sentence_transformer_async",
    "AsyncEmbeddingStore": "sci_etl_core.embeddings.store_base",
    "EmbeddingChunk": "sci_etl_core.embeddings.store_base",
    "SearchHit": "sci_etl_core.embeddings.store_base",
    "InMemoryEmbeddingStore": "sci_etl_core.embeddings.store_memory",
    "AsyncSqliteEmbeddingStore": "sci_etl_core.embeddings.store_sqlite_async",
    "ConfigurationError": "sci_etl_core.exceptions",
    "EmbeddingError": "sci_etl_core.exceptions",
    "EmbeddingStoreError": "sci_etl_core.exceptions",
    "ExtractionError": "sci_etl_core.exceptions",
    "LLMCacheError": "sci_etl_core.exceptions",
    "LLMError": "sci_etl_core.exceptions",
    "MalformedResponseError": "sci_etl_core.exceptions",
    "ParsingError": "sci_etl_core.exceptions",
    "PipelineAborted": "sci_etl_core.exceptions",
    "PipelineInterrupted": "sci_etl_core.exceptions",
    "SciEtlError": "sci_etl_core.exceptions",
    "SearchError": "sci_etl_core.exceptions",
    "SearchQueryError": "sci_etl_core.exceptions",
    "SearchStoreError": "sci_etl_core.exceptions",
    "StaleCursorError": "sci_etl_core.exceptions",
    "StateStoreError": "sci_etl_core.exceptions",
    "UpstreamError": "sci_etl_core.exceptions",
    "AsyncExporter": "sci_etl_core.exporters.async_base",
    "Exporter": "sci_etl_core.exporters.base",
    "AsyncCsvUpsertExporter": "sci_etl_core.exporters.csv_async",
    "AsyncPlotly3DExporter": "sci_etl_core.exporters.plotly_async",
    "ScatterPlotConfig": "sci_etl_core.exporters.plotly_async",
    "AsyncSqlTableExporter": "sci_etl_core.exporters.sql_async",
    "AsyncExtractor": "sci_etl_core.extractors.async_base",
    "OffsetListing": "sci_etl_core.extractors.async_base",
    "AsyncArxivExtractor": "sci_etl_core.extractors.arxiv_async",
    "AsyncOpenAlexExtractor": "sci_etl_core.extractors.openalex_async",
    "AsyncPubMedExtractor": "sci_etl_core.extractors.pubmed_async",
    "AsyncSemanticScholarExtractor": "sci_etl_core.extractors.semantic_scholar_async",
    "Extractor": "sci_etl_core.extractors.base",
    "AsyncCompositeIngestor": "sci_etl_core.ingest_async",
    "MEMORY_FAULTS": "sci_etl_core.ingest_protocol",
    "MemoryIngestor": "sci_etl_core.ingest_protocol",
    "SyncLLMClientAdapter": "sci_etl_core.llm._adapters",
    "AsyncLLMClient": "sci_etl_core.llm.async_base",
    "AsyncLLMResponseCache": "sci_etl_core.llm.cache_async",
    "AsyncSqliteLLMResponseCache": "sci_etl_core.llm.cache_async",
    "CachingLLMClient": "sci_etl_core.llm.cache_async",
    "InMemoryLLMResponseCache": "sci_etl_core.llm.cache_async",
    "EntityExtractor": "sci_etl_core.llm.base",
    "LLMClient": "sci_etl_core.llm.base",
    "RelevanceFilter": "sci_etl_core.llm.base",
    "AsyncEntityExtractor": "sci_etl_core.llm.extraction_async",
    "AsyncLLMEntityExtractor": "sci_etl_core.llm.extraction_async",
    "AsyncOpenAICompatibleClient": "sci_etl_core.llm.openai_compatible_async",
    "AsyncLLMRelevanceFilter": "sci_etl_core.llm.relevance_async",
    "AsyncRelevanceFilter": "sci_etl_core.llm.relevance_async",
    "AsyncEmbeddingRelevanceFilter": "sci_etl_core.llm.relevance_embedding_async",
    "configure_logging": "sci_etl_core.log_utils",
    "RunMetrics": "sci_etl_core.observability",
    "ListingPage": "sci_etl_core.models",
    "PipelineMetadata": "sci_etl_core.models",
    "RawRecord": "sci_etl_core.models",
    "TokenUsage": "sci_etl_core.models",
    "Parser": "sci_etl_core.parsers.base",
    "TableParser": "sci_etl_core.parsers.base",
    "ETLPipeline": "sci_etl_core.pipeline",
    "AsyncETLPipeline": "sci_etl_core.pipeline_async",
    "Processor": "sci_etl_core.processors.base",
    "ProcessorChain": "sci_etl_core.processors.base",
    "ShutdownSignal": "sci_etl_core.signals",
    "AsyncStateManager": "sci_etl_core.state.async_base",
    "AsyncFileStateManager": "sci_etl_core.state.async_file_state",
    "StateManager": "sci_etl_core.state.base",
    "AsyncSqliteStateManager": "sci_etl_core.state.sqlite_async",
}

__all__ = sorted(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core._adapters import (
        SyncEntityExtractorAdapter,
        SyncExporterAdapter,
        SyncExtractorAdapter,
        SyncRelevanceFilterAdapter,
        SyncStateManagerAdapter,
    )
    from sci_etl_core.config import (
        BaseAppConfig,
        HttpConfig,
        LLMConfig,
        PipelineConfig,
        RateLimitConfig,
        SearchConfig,
        load_config,
    )
    from sci_etl_core.config_async import load_config_async
    from sci_etl_core.discovery import DiscoveryResult, Facet
    from sci_etl_core.embeddings.async_base import AsyncEmbedder
    from sci_etl_core.embeddings.chunking import SlidingWindowChunker, TextChunker
    from sci_etl_core.embeddings.finder_async import AsyncSimilarArticleFinder
    from sci_etl_core.embeddings.ingest_async import AsyncChunkIngestor
    from sci_etl_core.embeddings.openai_compatible_async import AsyncOpenAIEmbedder
    from sci_etl_core.embeddings.sentence_transformer_async import AsyncSentenceTransformerEmbedder
    from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, EmbeddingChunk, SearchHit
    from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
    from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
    from sci_etl_core.exceptions import (
        ConfigurationError,
        EmbeddingError,
        EmbeddingStoreError,
        ExtractionError,
        LLMCacheError,
        LLMError,
        MalformedResponseError,
        ParsingError,
        PipelineAborted,
        PipelineInterrupted,
        SciEtlError,
        SearchError,
        SearchQueryError,
        SearchStoreError,
        StaleCursorError,
        StateStoreError,
        UpstreamError,
    )
    from sci_etl_core.exporters.async_base import AsyncExporter
    from sci_etl_core.exporters.base import Exporter
    from sci_etl_core.exporters.csv_async import AsyncCsvUpsertExporter
    from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter, ScatterPlotConfig
    from sci_etl_core.exporters.sql_async import AsyncSqlTableExporter
    from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
    from sci_etl_core.extractors.async_base import AsyncExtractor, OffsetListing
    from sci_etl_core.extractors.base import Extractor
    from sci_etl_core.extractors.openalex_async import AsyncOpenAlexExtractor
    from sci_etl_core.extractors.pubmed_async import AsyncPubMedExtractor
    from sci_etl_core.extractors.semantic_scholar_async import AsyncSemanticScholarExtractor
    from sci_etl_core.ingest_async import AsyncCompositeIngestor
    from sci_etl_core.ingest_protocol import MEMORY_FAULTS, MemoryIngestor
    from sci_etl_core.llm._adapters import SyncLLMClientAdapter
    from sci_etl_core.llm.async_base import AsyncLLMClient
    from sci_etl_core.llm.base import EntityExtractor, LLMClient, RelevanceFilter
    from sci_etl_core.llm.cache_async import (
        AsyncLLMResponseCache,
        AsyncSqliteLLMResponseCache,
        CachingLLMClient,
        InMemoryLLMResponseCache,
    )
    from sci_etl_core.llm.extraction_async import AsyncEntityExtractor, AsyncLLMEntityExtractor
    from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient
    from sci_etl_core.llm.relevance_async import AsyncLLMRelevanceFilter, AsyncRelevanceFilter
    from sci_etl_core.llm.relevance_embedding_async import AsyncEmbeddingRelevanceFilter
    from sci_etl_core.log_utils import configure_logging
    from sci_etl_core.models import ListingPage, PipelineMetadata, RawRecord, TokenUsage
    from sci_etl_core.observability import RunMetrics
    from sci_etl_core.parsers.base import Parser, TableParser
    from sci_etl_core.pipeline import ETLPipeline
    from sci_etl_core.pipeline_async import AsyncETLPipeline
    from sci_etl_core.processors.base import Processor, ProcessorChain
    from sci_etl_core.signals import ShutdownSignal
    from sci_etl_core.state.async_base import AsyncStateManager
    from sci_etl_core.state.async_file_state import AsyncFileStateManager
    from sci_etl_core.state.base import StateManager
    from sci_etl_core.state.sqlite_async import AsyncSqliteStateManager
