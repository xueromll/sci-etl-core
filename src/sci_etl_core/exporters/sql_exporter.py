from __future__ import annotations

import pandas as pd

from sci_etl_core.exporters.base import Exporter


class SqlTableExporter(Exporter):
    def __init__(self, table_name: str, if_exists: str = "append") -> None:
        self._table_name = table_name
        self._if_exists = if_exists

    def export(self, data: pd.DataFrame, destination: str) -> None:
        from sqlalchemy import create_engine

        engine = create_engine(destination)
        data.to_sql(self._table_name, engine, if_exists=self._if_exists, index=False)
