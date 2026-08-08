from __future__ import annotations

import pandas as pd

from sci_etl_core.exporters.sql_exporter import SqlTableExporter


class TestSqlTableExporter:
    def test_creates_engine_and_writes_frame(self, mocker):
        engine = mocker.MagicMock()
        create_engine = mocker.patch("sqlalchemy.create_engine", return_value=engine)
        frame = mocker.MagicMock(spec=pd.DataFrame)
        exporter = SqlTableExporter(table_name="t", if_exists="replace")
        exporter.export(frame, "sqlite:///:memory:")
        create_engine.assert_called_once_with("sqlite:///:memory:")
        frame.to_sql.assert_called_once_with("t", engine, if_exists="replace", index=False)
