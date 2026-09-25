from __future__ import annotations

import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine

from sci_etl_core._deprecation import warn_deprecated
from sci_etl_core.exporters.async_base import AsyncExporter


class AsyncSqlTableExporter(AsyncExporter):
    """Write a dataframe to a SQL table through an async SQLAlchemy engine. Needs the ``sql`` extra.

    It takes a ``DataFrame``, not the pipeline's ``list[dict]`` of entities, so
    it serves post-processing output rather than
    :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` directly.

    .. deprecated:: 0.5.0
        Constructing it emits a :class:`DeprecationWarning`. It will be
        removed in 0.6.0; use
        :class:`~sci_etl_core.processors.sinks.SqlTableSink` instead.
    """

    def __init__(self, table_name: str, if_exists: str = "append") -> None:
        """Target ``table_name``; ``if_exists`` is passed to ``DataFrame.to_sql``."""
        warn_deprecated("AsyncSqlTableExporter", "use sci_etl_core.processors.sinks.SqlTableSink instead")
        self._table_name = table_name
        self._if_exists = if_exists

    async def export(self, data: pd.DataFrame, destination: str) -> None:
        """Write ``data`` without its index to the database at the async URL ``destination``.

        An engine is created and disposed for each call, and the write runs in
        one transaction.
        """
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
