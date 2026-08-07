from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Exporter(ABC):
    @abstractmethod
    def export(self, data: Any, destination: str) -> None:
        """Persist data to the given destination."""
