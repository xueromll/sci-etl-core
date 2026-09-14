from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from sci_etl_core.models import TokenUsage


class AsyncEmbedder(ABC):
    """Turn text into dense vectors so records can be matched by meaning.

    A single call embeds a batch of texts and returns one vector per input, in
    the same order. Vectors are plain ``list[float]`` to keep the contract free
    of any numeric-library dependency.
    """

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text, preserving order."""

    @property
    def usage(self) -> TokenUsage | None:
        """Tokens this embedder has used so far, or ``None`` when it does not track usage."""
        return None
