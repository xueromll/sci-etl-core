from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AsyncExporter(ABC):
    @abstractmethod
    async def export(self, data: Any, destination: str) -> None:
        """Persist data to the given destination without blocking the event loop."""
