from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core._deprecation import is_bundled, warn_deprecated


class AsyncExporter(ABC):
    """Contract for a sink that persists extracted data.

    :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` calls :meth:`export`
    once per relevant record with that record's entities as a
    ``list[dict[str, Any]]``, possibly from several records concurrently. An
    implementation used in a pipeline must accept that shape and serialize its
    own writes.

    .. deprecated:: 0.5.0
        :meth:`export` is replaced in 0.6.0 by an exporter lifecycle of
        ``open``, ``write`` per record, ``flush`` per page, and ``aclose``.
        Subclassing it outside sci-etl-core emits a
        :class:`DeprecationWarning` as advance notice; there is nothing to
        migrate to before 0.6.0.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_bundled(cls):
            warn_deprecated(
                "AsyncExporter.export",
                "sci-etl-core 0.6.0 replaces it with the open, write, flush, and aclose lifecycle",
                stacklevel=3,
            )

    @abstractmethod
    async def export(self, data: Any, destination: str) -> None:
        """Persist data to the given destination without blocking the event loop."""
