from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AsyncExporter(ABC):
    """Contract for a sink that persists extracted data.

    :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` calls :meth:`export`
    once per relevant record with that record's entities as a
    ``list[dict[str, Any]]``, possibly from several records concurrently. An
    implementation used in a pipeline must accept that shape and serialize its
    own writes.
    """

    @abstractmethod
    async def export(self, data: Any, destination: str) -> None:
        """Persist data to the given destination without blocking the event loop."""
