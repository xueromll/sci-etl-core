"""Every name 0.5.0 deprecates warns, names its package, and says what replaces it."""

from __future__ import annotations

import sqlite3
import types
import warnings
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import Any

import pandas as pd
import pytest

from sci_etl_core import (
    AsyncCsvUpsertExporter,
    AsyncETLPipeline,
    AsyncExporter,
    EntityExtractor,
    Exporter,
    Extractor,
    LLMClient,
    RelevanceFilter,
    ShutdownSignal,
    StateManager,
    SyncEntityExtractorAdapter,
    SyncExporterAdapter,
    SyncExtractorAdapter,
    SyncLLMClientAdapter,
    SyncRelevanceFilterAdapter,
    SyncStateManagerAdapter,
    UpstreamError,
    configure_logging,
)
from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter, ScatterPlotConfig
from sci_etl_core.exporters.sql_async import AsyncSqlTableExporter
from sci_etl_core.extractors import AsyncOpenAlexExtractor, LegacyExtractorAdapter
from sci_etl_core.models import RawRecord
from sci_etl_core.processors import DefaultKeyNormalizer

REMOVAL = "is deprecated and will be removed in sci-etl-core 0.6.0"


@contextmanager
def _committing(database: Any) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(database)) as connection:
        yield connection
        connection.commit()


class _OldExtractor:
    def __init__(self, payload: bytes | None) -> None:
        self.payload = payload

    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return self.payload

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        return [RawRecord(record_id="a", title="t", abstract="x")], 1

    async def fetch_full_text(self, record: RawRecord) -> str:
        return "text"


class _BlockingExtractor(Extractor):
    def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return None

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        return [], 0

    def fetch_full_text(self, record: RawRecord) -> str:
        return ""


def _collaborators(mocker: Any) -> list[Any]:
    return [mocker.Mock() for _ in range(5)]


class TestLegacyExtractorAdapter:
    @pytest.mark.asyncio
    async def test_it_warns_and_pages_the_old_contract_by_offset(self):
        with pytest.warns(DeprecationWarning, match=f"LegacyExtractorAdapter {REMOVAL}; implement AsyncExtractor"):
            adapter = LegacyExtractorAdapter(_OldExtractor(b"payload"))
        page = await adapter.fetch_page("q", "5", 10)
        assert (page.entries, page.next_cursor) == (1, "6")
        assert adapter.cursor_for_offset(6) == "6"
        assert await adapter.fetch_full_text(page.records[0]) == "text"

    @pytest.mark.asyncio
    async def test_a_missing_payload_is_an_upstream_error(self):
        with pytest.warns(DeprecationWarning, match="LegacyExtractorAdapter"):
            adapter = LegacyExtractorAdapter(_OldExtractor(None))
        with pytest.raises(UpstreamError, match="offset 0 returned no payload"):
            await adapter.fetch_page("q", None, 10)


class TestBlockingContracts:
    @pytest.mark.parametrize(
        "contract", [Extractor, StateManager, Exporter, LLMClient, RelevanceFilter, EntityExtractor]
    )
    def test_subclassing_a_blocking_contract_outside_the_library_warns(self, contract):
        with pytest.warns(DeprecationWarning, match=f"The blocking {contract.__name__} contract {REMOVAL}"):
            type("Custom", (contract,), {})

    @pytest.mark.parametrize(
        "contract", [Extractor, StateManager, Exporter, LLMClient, RelevanceFilter, EntityExtractor]
    )
    def test_a_subclass_inside_the_library_raises_no_warning(self, contract):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            type("Bundled", (contract,), {"__module__": "sci_etl_core.example"})

    @pytest.mark.parametrize(
        "adapter",
        [
            SyncExtractorAdapter,
            SyncRelevanceFilterAdapter,
            SyncEntityExtractorAdapter,
            SyncExporterAdapter,
            SyncStateManagerAdapter,
            SyncLLMClientAdapter,
        ],
    )
    def test_every_adapter_warns_when_constructed(self, adapter):
        with pytest.warns(DeprecationWarning, match=f"{adapter.__name__} {REMOVAL}"):
            adapter(object())

    @pytest.mark.asyncio
    async def test_the_extractor_adapter_reports_a_missing_payload(self):
        with pytest.warns(DeprecationWarning, match="SyncExtractorAdapter"):
            adapter = SyncExtractorAdapter(_BlockingExtractor())
        with pytest.raises(UpstreamError, match="returned no payload"):
            await adapter.fetch_page("q", None, 10)


class TestExporters:
    def test_subclassing_the_async_exporter_outside_the_library_warns_about_export(self):
        message = f"AsyncExporter.export {REMOVAL}; .*open, write, flush, and aclose"
        with pytest.warns(DeprecationWarning, match=message):
            type("Custom", (AsyncExporter,), {})

    def test_the_bundled_exporters_import_without_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            type("Bundled", (AsyncExporter,), {"__module__": "sci_etl_core.exporters.example"})

    def test_the_csv_upsert_exporter_warns_and_names_its_0_6_replacement(self):
        with pytest.warns(DeprecationWarning, match=r"AsyncCsvUpsertExporter .*AsyncCsvExporter \(0\.6\.0\)"):
            AsyncCsvUpsertExporter("key", ["value"], DefaultKeyNormalizer())

    def test_the_table_exporters_point_to_the_sinks(self):
        with pytest.warns(DeprecationWarning, match="use sci_etl_core.processors.sinks.SqlTableSink"):
            AsyncSqlTableExporter("table")
        with pytest.warns(DeprecationWarning, match="use sci_etl_core.processors.sinks.Plotly3DSink"):
            AsyncPlotly3DExporter(ScatterPlotConfig("x", "y", "z", "c"))


class TestArguments:
    def test_the_pipeline_destination_and_logger_warn(self, mocker):
        with pytest.warns(DeprecationWarning, match=r"AsyncETLPipeline\(destination=\) " + REMOVAL):
            AsyncETLPipeline(*_collaborators(mocker), destination="out.csv")
        with pytest.warns(DeprecationWarning, match=r"AsyncETLPipeline\(logger=\) " + REMOVAL):
            AsyncETLPipeline(*_collaborators(mocker), logger=print)

    def test_a_pipeline_without_them_raises_no_warning(self, mocker):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            AsyncETLPipeline(*_collaborators(mocker))

    def test_component_logger_arguments_warn(self, mocker):
        with pytest.warns(DeprecationWarning, match=r"ShutdownSignal\(logger=\) " + REMOVAL):
            ShutdownSignal(signals=(), logger=print)
        with pytest.warns(DeprecationWarning, match=r"AsyncOpenAlexExtractor\(logger=\) " + REMOVAL):
            AsyncOpenAlexExtractor(mocker.Mock(), logger=print)

    def test_configure_logging_warns(self, tmp_path):
        with pytest.warns(DeprecationWarning, match=f"configure_logging {REMOVAL}"):
            logger = configure_logging("sci-etl-deprecation-test", tmp_path / "run.log")
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


class TestSinks:
    def test_the_sql_sink_writes_the_table_in_one_transaction_and_disposes_the_engine(self, tmp_path, mocker):
        from sci_etl_core.processors import sinks

        database = tmp_path / "catalogue.db"
        engines: list[Any] = []

        def create_engine(url: str) -> Any:
            engine = mocker.Mock()
            engine.begin = lambda: _committing(database)
            engines.append((url, engine))
            return engine

        mocker.patch.object(sinks, "import_module", return_value=types.SimpleNamespace(create_engine=create_engine))
        sink = sinks.SqlTableSink("sqlite:///catalogue.db", "galaxies", if_exists="replace")
        sink.write(pd.DataFrame({"name": ["UDG1"], "size": [1.5]}))
        sink.write(pd.DataFrame({"name": ["UDG2"], "size": [2.5]}))

        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT name, size FROM galaxies").fetchall() == [("UDG2", 2.5)]
        assert [url for url, _ in engines] == ["sqlite:///catalogue.db"] * 2
        assert all(engine.dispose.call_count == 1 for _, engine in engines)

    def test_the_plotly_sink_writes_html_and_skips_a_table_without_coordinates(self, tmp_path):
        from sci_etl_core.processors.sinks import Plotly3DSink

        path = tmp_path / "plot.html"
        sink = Plotly3DSink(ScatterPlotConfig("x", "y", "z", "c"), path)
        sink.write(pd.DataFrame({"x": [None], "y": [1.0], "z": [1.0], "c": [1.0]}))
        assert not path.exists()
        sink.write(pd.DataFrame({"x": [1.0], "y": [2.0], "z": [3.0], "c": [4.0]}))
        assert "<html>" in path.read_text(encoding="utf-8")

    def test_the_sinks_module_imports_without_the_optional_libraries(self):
        import sci_etl_core.processors.sinks as sinks

        assert {"TableSink", "SqlTableSink", "Plotly3DSink"} <= set(dir(sinks))
