from __future__ import annotations

from abc import ABC, abstractmethod


class Parser(ABC):
    @abstractmethod
    def extract_text(self, content: bytes) -> str:
        """Extract plain text from raw document bytes."""


class TableParser(ABC):
    @abstractmethod
    def extract_tables(self, content: bytes) -> str:
        """Extract a text representation of tables found in raw document bytes."""
