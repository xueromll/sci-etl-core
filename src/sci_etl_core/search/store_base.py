from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchDocument:
    """One article's searchable text, as a single indexable unit.

    The lexical index holds one document per record, while the vector memory
    holds one row per chunk. BM25 saturates on term frequency and normalizes by
    document length, so chunking a document would fragment its statistics and
    inflate short chunks.
    """

    record_id: str
    title: str = ""
    abstract: str = ""
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
