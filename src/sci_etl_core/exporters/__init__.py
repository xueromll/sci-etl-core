from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "Exporter": "sci_etl_core.exporters.base",
    "AsyncExporter": "sci_etl_core.exporters.async_base",
    "ScatterPlotConfig": "sci_etl_core.exporters.plotly_async",
    "AsyncCsvUpsertExporter": "sci_etl_core.exporters.csv_async",
    "AsyncPlotly3DExporter": "sci_etl_core.exporters.plotly_async",
    "AsyncSqlTableExporter": "sci_etl_core.exporters.sql_async",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.exporters.base import Exporter
    from sci_etl_core.exporters.async_base import AsyncExporter
    from sci_etl_core.exporters.plotly_async import ScatterPlotConfig
    from sci_etl_core.exporters.csv_async import AsyncCsvUpsertExporter
    from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter
    from sci_etl_core.exporters.sql_async import AsyncSqlTableExporter
