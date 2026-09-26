from __future__ import annotations

import sqlite3
import types
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import Any

import pandas as pd

from sci_etl_core.processors.sinks import ScatterPlotConfig


@contextmanager
def _committing(database: Any) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(database)) as connection:
        yield connection
        connection.commit()


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
