from __future__ import annotations

from typing import Protocol

from sci_etl_core.exceptions import EmbeddingError, EmbeddingStoreError, SearchStoreError
from sci_etl_core.models import RawRecord

MEMORY_FAULTS: tuple[type[Exception], ...] = (EmbeddingError, EmbeddingStoreError, SearchStoreError)
"""The storage and embedding faults a memory ingest logs instead of failing the record.

``SearchStoreError`` is listed rather than ``SearchError``, so a ``SearchQueryError`` is never mistaken for a
storage fault.
"""


class MemoryIngestor(Protocol):
    """Stores a relevant record's full text in a memory backend.

    A memory backend is the vector memory, the text search index, or both
    through :class:`~sci_etl_core.ingest_async.AsyncCompositeIngestor`. The
    exceptions in :data:`MEMORY_FAULTS` are storage or embedding faults: the
    pipeline logs them and still exports the record's entities. Any other
    exception, including a :class:`~sci_etl_core.exceptions.SearchQueryError`,
    fails the record.
    """

    async def ingest(self, record: RawRecord, text: str) -> int:
        """Replace what is stored for ``record`` with ``text``, returning how many units were stored."""
