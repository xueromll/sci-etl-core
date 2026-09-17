from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Exporter(ABC):
    """Blocking counterpart of :class:`~sci_etl_core.exporters.async_base.AsyncExporter`.

    Wrap an implementation in
    :class:`~sci_etl_core._adapters.SyncExporterAdapter` to use it in a
    pipeline.
    """

    @abstractmethod
    def export(self, data: Any, destination: str) -> None:
        """Persist data to the given destination."""
