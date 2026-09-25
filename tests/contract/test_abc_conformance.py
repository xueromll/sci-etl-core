from __future__ import annotations

import inspect

import pytest

from sci_etl_core._adapters import (
    SyncEntityExtractorAdapter,
    SyncExporterAdapter,
    SyncExtractorAdapter,
    SyncRelevanceFilterAdapter,
    SyncStateManagerAdapter,
)
from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.chunking import SlidingWindowChunker, TextChunker
from sci_etl_core.embeddings.openai_compatible_async import AsyncOpenAIEmbedder
from sci_etl_core.embeddings.sentence_transformer_async import AsyncSentenceTransformerEmbedder
from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.exporters.csv_async import AsyncCsvUpsertExporter
from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter
from sci_etl_core.exporters.sql_async import AsyncSqlTableExporter
from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.extractors.openalex_async import AsyncOpenAlexExtractor
from sci_etl_core.extractors.pubmed_async import AsyncPubMedExtractor
from sci_etl_core.extractors.semantic_scholar_async import AsyncSemanticScholarExtractor
from sci_etl_core.llm._adapters import SyncLLMClientAdapter
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor, AsyncLLMEntityExtractor
from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient
from sci_etl_core.llm.relevance_async import AsyncLLMRelevanceFilter, AsyncRelevanceFilter
from sci_etl_core.llm.relevance_embedding_async import AsyncEmbeddingRelevanceFilter
from sci_etl_core.parsers.base import Parser, TableParser
from sci_etl_core.parsers.html import HtmlTextParser
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser
from sci_etl_core.processors.base import Processor, ProcessorChain
from sci_etl_core.processors.clustering import ClusteringStep
from sci_etl_core.processors.dedup import DeduplicationStep
from sci_etl_core.processors.normalization import (
    DefaultKeyNormalizer,
    KeyNormalizer,
    NormalizationStep,
)
from sci_etl_core.processors.quality import CompletenessStep, QualityFlagStep
from sci_etl_core.processors.validation import (
    CompositeValidator,
    KeywordExclusionValidator,
    NumericRangeValidator,
    RecordValidator,
)
from sci_etl_core.search.edges import AsyncEdgeSource, EmbeddingEdgeSource, MetadataEdgeSource
from sci_etl_core.search.store_base import AsyncTextSearchStore
from sci_etl_core.search.store_memory import InMemoryTextSearchStore
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.async_file_state import AsyncFileStateManager
from sci_etl_core.state.sqlite_async import AsyncSqliteStateManager

CASES: list[tuple[type, type]] = [
    (AsyncExtractor, AsyncArxivExtractor),
    (AsyncExtractor, AsyncOpenAlexExtractor),
    (AsyncExtractor, AsyncPubMedExtractor),
    (AsyncExtractor, AsyncSemanticScholarExtractor),
    (Parser, HtmlTextParser),
    (Parser, LatexTarballParser),
    (Parser, PdfPlumberParser),
    (TableParser, PdfPlumberParser),
    (AsyncLLMClient, AsyncOpenAICompatibleClient),
    (Processor, ProcessorChain),
    (Processor, ClusteringStep),
    (Processor, DeduplicationStep),
    (Processor, NormalizationStep),
    (Processor, CompletenessStep),
    (Processor, QualityFlagStep),
    (AsyncExporter, AsyncCsvUpsertExporter),
    (AsyncExporter, AsyncPlotly3DExporter),
    (AsyncExporter, AsyncSqlTableExporter),
    (AsyncStateManager, AsyncFileStateManager),
    (AsyncExtractor, SyncExtractorAdapter),
    (AsyncRelevanceFilter, SyncRelevanceFilterAdapter),
    (AsyncEntityExtractor, SyncEntityExtractorAdapter),
    (AsyncExporter, SyncExporterAdapter),
    (AsyncStateManager, SyncStateManagerAdapter),
    (AsyncLLMClient, SyncLLMClientAdapter),
    (AsyncRelevanceFilter, AsyncLLMRelevanceFilter),
    (AsyncRelevanceFilter, AsyncEmbeddingRelevanceFilter),
    (AsyncEntityExtractor, AsyncLLMEntityExtractor),
    (AsyncStateManager, AsyncSqliteStateManager),
    (AsyncEmbedder, AsyncOpenAIEmbedder),
    (AsyncEmbedder, AsyncSentenceTransformerEmbedder),
    (AsyncEmbeddingStore, InMemoryEmbeddingStore),
    (AsyncEmbeddingStore, AsyncSqliteEmbeddingStore),
    (AsyncTextSearchStore, InMemoryTextSearchStore),
    (AsyncTextSearchStore, AsyncSqliteFts5Store),
    (AsyncEdgeSource, EmbeddingEdgeSource),
    (AsyncEdgeSource, MetadataEdgeSource),
    (TextChunker, SlidingWindowChunker),
    (KeyNormalizer, DefaultKeyNormalizer),
    (RecordValidator, KeywordExclusionValidator),
    (RecordValidator, NumericRangeValidator),
    (RecordValidator, CompositeValidator),
]

_IDS = [f"{abc.__name__}-{concrete.__name__}" for abc, concrete in CASES]


@pytest.mark.parametrize(("abc", "concrete"), CASES, ids=_IDS)
class TestAbcConformance:
    def test_is_registered_subclass(self, abc, concrete):
        assert issubclass(concrete, abc)

    def test_is_not_abstract(self, abc, concrete):
        assert not inspect.isabstract(concrete)

    def test_all_abstract_methods_are_overridden(self, abc, concrete):
        for name in getattr(abc, "__abstractmethods__", frozenset()):
            overridden = getattr(concrete, name, None)
            assert overridden is not None
            assert overridden is not getattr(abc, name, None)

    def test_overridden_methods_are_callable(self, abc, concrete):
        for name in getattr(abc, "__abstractmethods__", frozenset()):
            member = getattr(concrete, name)
            assert isinstance(member, property) or callable(member)
