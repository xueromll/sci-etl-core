from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "AsyncExporter": "sci_etl_core.exporters.async_base",
    "AsyncCsvExporter": "sci_etl_core.exporters.csv_async",
    "AsyncJsonlExporter": "sci_etl_core.exporters.jsonl_async",
    "read_jsonl_export": "sci_etl_core.exporters.jsonl_async",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.exporters.async_base import AsyncExporter
    from sci_etl_core.exporters.csv_async import AsyncCsvExporter
    from sci_etl_core.exporters.jsonl_async import AsyncJsonlExporter, read_jsonl_export
