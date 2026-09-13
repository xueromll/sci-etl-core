from __future__ import annotations

from abc import ABC, abstractmethod


class Parser(ABC):
    @abstractmethod
    def extract_text(self, content: bytes) -> str:
        """Extract plain text from raw document bytes.

        Raises:
            ParsingError: The bytes are not a document this parser can read.
                Callers such as :class:`AsyncArxivExtractor` rely on this type
                to tell an unreadable artifact apart from a programming error.
        """


class TableParser(ABC):
    @abstractmethod
    def extract_tables(self, content: bytes) -> str:
        """Extract a text representation of tables found in raw document bytes."""
