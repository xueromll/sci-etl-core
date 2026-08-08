from __future__ import annotations

from abc import ABC, abstractmethod

from sci_etl_core.models import RawRecord


class AsyncExtractor(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        """Fetch a raw listing page from the source."""

    @abstractmethod
    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse a raw listing into records, skipping already-seen ids."""

    @abstractmethod
    async def fetch_full_text(self, record: RawRecord) -> str:
        """Retrieve the best-available full text for a record."""
