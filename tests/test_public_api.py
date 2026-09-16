from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import sci_etl_core

SRC = Path(__file__).resolve().parents[1] / "src"

PACKAGES = [
    "sci_etl_core",
    "sci_etl_core.embeddings",
    "sci_etl_core.exporters",
    "sci_etl_core.extractors",
    "sci_etl_core.llm",
    "sci_etl_core.parsers",
    "sci_etl_core.processors",
    "sci_etl_core.search",
    "sci_etl_core.state",
]

# numpy is absent from this list on purpose: pandas, a core dependency,
# requires it, so no real install is ever without it.
_OPTIONAL = (
    "aiofiles",
    "aiolimiter",
    "httpx",
    "openai",
    "pdfplumber",
    "plotly",
    "requests",
    "sentence_transformers",
    "sklearn",
    "sqlalchemy",
    "tiktoken",
)

_PROBE = textwrap.dedent(
    """
    import importlib.abc
    import sys

    blocked = set(filter(None, sys.argv[1].split(",")))

    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    sys.meta_path.insert(0, Blocker())
    exec(sys.argv[2])
    """
)


def _run_with_only(allowed: set[str], code: str) -> subprocess.CompletedProcess[str]:
    blocked = ",".join(sorted(set(_OPTIONAL) - allowed))
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-c", _PROBE, blocked, textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_every_public_name_resolves():
    missing = [name for name in sci_etl_core.__all__ if not hasattr(sci_etl_core, name)]
    assert missing == []


@pytest.mark.parametrize(
    "name, module",
    [
        ("AsyncETLPipeline", "sci_etl_core.pipeline_async"),
        ("AsyncCompositeIngestor", "sci_etl_core.ingest_async"),
        ("MEMORY_FAULTS", "sci_etl_core.ingest_protocol"),
        ("AsyncSqliteStateManager", "sci_etl_core.state.sqlite_async"),
        ("RateLimitConfig", "sci_etl_core.config"),
        ("ShutdownSignal", "sci_etl_core.signals"),
        ("SyncExtractorAdapter", "sci_etl_core._adapters"),
        ("SyncLLMClientAdapter", "sci_etl_core.llm._adapters"),
        ("EntityExtractor", "sci_etl_core.llm.base"),
        ("RelevanceFilter", "sci_etl_core.llm.base"),
    ],
)
def test_package_root_reexports_the_defining_object(name, module):
    assert getattr(sci_etl_core, name) is getattr(importlib.import_module(module), name)


@pytest.mark.parametrize("package", PACKAGES)
class TestLazyExports:
    def test_exports_resolve_and_are_listed_by_dir(self, package):
        module = importlib.import_module(package)
        for name in module.__all__:
            assert getattr(module, name) is not None
        assert set(module.__all__) <= set(dir(module))

    def test_unknown_attribute_raises_attribute_error(self, package):
        module = importlib.import_module(package)
        with pytest.raises(AttributeError, match="has no attribute 'missing_name'"):
            _ = module.missing_name

    def test_type_checking_imports_match_the_export_map(self, package):
        module = importlib.import_module(package)
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
                for statement in node.body:
                    assert isinstance(statement, ast.ImportFrom)
                    for alias in statement.names:
                        imported[alias.name] = statement.module
        assert imported == module._EXPORTS


class TestInstallFootprint:
    def test_core_components_import_without_optional_dependencies(self):
        result = _run_with_only(
            set(),
            """
            import sci_etl_core
            from sci_etl_core import (
                AsyncETLPipeline,
                AsyncFileStateManager,
                AsyncSqliteLLMResponseCache,
                AsyncSqliteStateManager,
                BaseAppConfig,
                CachingLLMClient,
                ETLPipeline,
                InMemoryLLMResponseCache,
                PipelineAborted,
                PipelineInterrupted,
                SearchConfig,
                ShutdownSignal,
                SyncExporterAdapter,
                load_config,
            )
            from sci_etl_core.embeddings import AsyncChunkIngestor, SlidingWindowChunker
            from sci_etl_core.parsers import HtmlTextParser, LatexTarballParser
            from sci_etl_core.processors import (
                DeduplicationStep,
                NormalizationStep,
                QualityFlagStep,
                TableLayoutStep,
                ValueClipStep,
            )
            from sci_etl_core.rate_limiter import HostRateLimiter
            from sci_etl_core.search import parse_query
            dir(sci_etl_core)
            """,
        )
        assert result.returncode == 0, result.stderr

    def test_a_component_missing_its_extra_names_the_package(self):
        result = _run_with_only(set(), "from sci_etl_core import AsyncArxivExtractor")
        assert result.returncode != 0
        assert "httpx" in result.stderr

    def test_quick_start_imports_with_the_async_llm_and_pdf_extras(self):
        result = _run_with_only(
            {"aiofiles", "aiolimiter", "httpx", "openai", "pdfplumber", "tiktoken"},
            """
            from sci_etl_core import (
                AsyncArxivExtractor,
                AsyncCsvUpsertExporter,
                AsyncLLMEntityExtractor,
                AsyncLLMRelevanceFilter,
                AsyncOpenAICompatibleClient,
            )
            from sci_etl_core.http_async import build_async_client
            from sci_etl_core.parsers import PdfPlumberParser
            """,
        )
        assert result.returncode == 0, result.stderr
