from __future__ import annotations

from abc import ABC, abstractmethod

from sci_etl_core.models import RawRecord


class AsyncExtractor(ABC):
    """Contract for a paged source of scientific records.

    :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` calls :meth:`search`
    once per page and never concurrently, :meth:`parse_listing` on the payload
    it returned, and :meth:`fetch_full_text` concurrently for the relevant
    records of that page.
    """

    @abstractmethod
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        """Fetch a raw listing page from the source.

        Raises:
            UpstreamError: The source could not be reached or answered with a
                server-side failure. Implementations must not collapse this
                into a falsy return value.
            ExtractionError: The source rejected the request permanently. The
                pipeline aborts on any ``ExtractionError`` from this method.
        """

    @abstractmethod
    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse a raw listing into records, skipping already-seen ids.

        Returns an empty result only when the payload is a valid listing that
        genuinely contains no entries.

        Raises:
            MalformedResponseError: The payload could not be interpreted.
        """

    @abstractmethod
    async def fetch_full_text(self, record: RawRecord) -> str:
        """Retrieve the best-available full text for a record."""
