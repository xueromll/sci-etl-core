from __future__ import annotations

from sci_etl_core.exporters import (
    AsyncCsvUpsertExporter,
    AsyncPlotly3DExporter,
    AsyncSqlTableExporter,
    CsvUpsertExporter,
    Exporter,
    Plotly3DExporter,
    ScatterPlotConfig,
    SqlTableExporter,
)
from sci_etl_core.extractors import ArxivExtractor, AsyncArxivExtractor, Extractor
from sci_etl_core.llm import (
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    EntityExtractor,
    LLMClient,
    LLMEntityExtractor,
    LLMRelevanceFilter,
    OpenAICompatibleClient,
    RelevanceFilter,
)
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.state import AsyncFileStateManager, FileStateManager, StateManager

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Extractor",
    "ArxivExtractor",
    "LLMClient",
    "OpenAICompatibleClient",
    "EntityExtractor",
    "LLMEntityExtractor",
    "RelevanceFilter",
    "LLMRelevanceFilter",
    "Exporter",
    "CsvUpsertExporter",
    "Plotly3DExporter",
    "SqlTableExporter",
    "ScatterPlotConfig",
    "StateManager",
    "FileStateManager",
    "ETLPipeline",
    "AsyncArxivExtractor",
    "AsyncOpenAICompatibleClient",
    "AsyncLLMEntityExtractor",
    "AsyncLLMRelevanceFilter",
    "AsyncCsvUpsertExporter",
    "AsyncPlotly3DExporter",
    "AsyncSqlTableExporter",
    "AsyncFileStateManager",
    "AsyncETLPipeline",
]
