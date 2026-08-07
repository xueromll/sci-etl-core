from __future__ import annotations

import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine

from sci_etl_core.exporters.async_base import AsyncExporter


class AsyncSqlTableExporter(AsyncExporter):
    def __init__(self, table_name: str, if_exists: str = "append") -> None:
        self._table_name = table_name
        self._if_exists = if_exists

    async def export(self, data: pd.DataFrame, destination: str) -> None:
        engine = create_async_engine(destination)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_conn: data.to_sql(
                        self._table_name, sync_conn, if_exists=self._if_exists, index=False
                    )
                )
        finally:
            await engine.dispose()
