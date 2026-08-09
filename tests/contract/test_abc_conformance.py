from __future__ import annotations

import inspect

import pytest

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.exporters.base import Exporter
from sci_etl_core.exporters.csv_async import AsyncCsvUpsertExporter
from sci_etl_core.exporters.csv_exporter import CsvUpsertExporter
from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter
from sci_etl_core.exporters.plotly_exporter import Plotly3DExporter
from sci_etl_core.exporters.sql_async import AsyncSqlTableExporter
from sci_etl_core.exporters.sql_exporter import SqlTableExporter
from sci_etl_core.extractors.arxiv import ArxivExtractor
from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.extractors.base import Extractor
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.base import LLMClient
from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient
from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient
from sci_etl_core.parsers.base import Parser, TableParser
from sci_etl_core.parsers.html import HtmlTextParser
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser
from sci_etl_core.processors.base import Processor, ProcessorChain
from sci_etl_core.processors.clustering import ClusteringStep
from sci_etl_core.processors.dedup import DeduplicationStep
from sci_etl_core.processors.normalization import NormalizationStep
from sci_etl_core.processors.quality import CompletenessStep, QualityFlagStep
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.async_file_state import AsyncFileStateManager
from sci_etl_core.state.base import StateManager
from sci_etl_core.state.file_state import FileStateManager

CASES: list[tuple[type, type]] = [
    (Extractor, ArxivExtractor),
    (AsyncExtractor, AsyncArxivExtractor),
    (Parser, HtmlTextParser),
    (Parser, LatexTarballParser),
    (Parser, PdfPlumberParser),
    (TableParser, PdfPlumberParser),
    (LLMClient, OpenAICompatibleClient),
    (AsyncLLMClient, AsyncOpenAICompatibleClient),
    (Processor, ProcessorChain),
    (Processor, ClusteringStep),
    (Processor, DeduplicationStep),
    (Processor, NormalizationStep),
    (Processor, CompletenessStep),
    (Processor, QualityFlagStep),
    (Exporter, CsvUpsertExporter),
    (Exporter, Plotly3DExporter),
    (Exporter, SqlTableExporter),
    (AsyncExporter, AsyncCsvUpsertExporter),
    (AsyncExporter, AsyncPlotly3DExporter),
    (AsyncExporter, AsyncSqlTableExporter),
    (StateManager, FileStateManager),
    (AsyncStateManager, AsyncFileStateManager),
]

_IDS = [f"{abc.__name__}-{concrete.__name__}" for abc, concrete in CASES]


@pytest.mark.parametrize("abc, concrete", CASES, ids=_IDS)
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
            assert callable(getattr(concrete, name))
