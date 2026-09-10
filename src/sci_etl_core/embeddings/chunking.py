from __future__ import annotations

from abc import ABC, abstractmethod


class TextChunker(ABC):
    """Split a document body into passages small enough to embed individually."""

    @abstractmethod
    def chunk(self, text: str) -> list[str]:
        """Return an ordered list of passages covering ``text``."""


class SlidingWindowChunker(TextChunker):
    """Fixed-size word windows with overlap between neighbors.

    Word counts approximate token counts (English runs ~1.3 tokens per word),
    so the default keeps each window comfortably under the 512-token ceiling of
    the common small embedding models. The overlap preserves context that would
    otherwise be severed at a window boundary.
    """

    def __init__(self, chunk_words: int = 350, overlap_words: int = 50) -> None:
        if chunk_words < 1:
            raise ValueError("chunk_words must be a positive integer")
        if not 0 <= overlap_words < chunk_words:
            raise ValueError("overlap_words must be in the range [0, chunk_words)")
        self._chunk_words = chunk_words
        self._overlap_words = overlap_words

    def chunk(self, text: str) -> list[str]:
        words = text.split()
        if not words:
            return []
        step = self._chunk_words - self._overlap_words
        chunks: list[str] = []
        for start in range(0, len(words), step):
            window = words[start : start + self._chunk_words]
            chunks.append(" ".join(window))
            if start + self._chunk_words >= len(words):
                break
        return chunks
