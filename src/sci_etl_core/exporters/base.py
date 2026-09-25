from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core._deprecation import is_bundled, warn_deprecated


class Exporter(ABC):
    """Blocking counterpart of :class:`~sci_etl_core.exporters.async_base.AsyncExporter`.

    Wrap an implementation in
    :class:`~sci_etl_core._adapters.SyncExporterAdapter` to use it in a
    pipeline.

    .. deprecated:: 0.5.0
        Subclassing it outside sci-etl-core emits a
        :class:`DeprecationWarning`. The blocking contracts will be removed in
        0.6.0; implement :class:`AsyncExporter` instead.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_bundled(cls):
            warn_deprecated("The blocking Exporter contract", "implement AsyncExporter instead", stacklevel=3)

    @abstractmethod
    def export(self, data: Any, destination: str) -> None:
        """Persist data to the given destination."""
