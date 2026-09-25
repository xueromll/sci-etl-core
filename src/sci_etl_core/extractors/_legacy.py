from __future__ import annotations

from typing import Protocol

from sci_etl_core._deprecation import warn_deprecated
from sci_etl_core.exceptions import UpstreamError
from sci_etl_core.extractors._offsets import decimal_cursor, offset_from_cursor, offset_page
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import ListingPage, RawRecord


class SearchAndParseExtractor(Protocol):
    """The extractor contract of sci-etl-core 0.4 and earlier."""

    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None: ...

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...


class LegacyExtractorAdapter(AsyncExtractor):
    """Run an extractor written against the 0.4 contract, ``search`` and ``parse_listing``, in a 0.5 pipeline.

    Its cursors are decimal offsets, so it supports ``newest_first`` runs. A
    page with no entries ends the listing, as it did in 0.4.

    .. deprecated:: 0.5.0
        Constructing it emits a :class:`DeprecationWarning`. It will be
        removed in 0.6.0; implement
        :meth:`~sci_etl_core.extractors.async_base.AsyncExtractor.fetch_page`
        instead.
    """

    def __init__(self, extractor: SearchAndParseExtractor) -> None:
        warn_deprecated("LegacyExtractorAdapter", "implement AsyncExtractor.fetch_page instead")
        self._extractor = extractor

    def cursor_for_offset(self, offset: int) -> str:
        return decimal_cursor(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        """Call the wrapped ``search`` at the cursor's offset and parse what it returns.

        Raises:
            UpstreamError: ``search`` returned no payload, or raised it.
            StaleCursorError: ``cursor`` is not a decimal offset.
            MalformedResponseError: ``parse_listing`` could not read the payload.
            ExtractionError: ``search`` raised it.
        """
        offset = offset_from_cursor(cursor)
        raw_listing = await self._extractor.search(query, page_size, offset)
        if not raw_listing:
            raise UpstreamError(f"The listing fetch at offset {offset} returned no payload")
        records, entries = self._extractor.parse_listing(raw_listing, set())
        return offset_page(records, entries, offset)

    async def fetch_full_text(self, record: RawRecord) -> str:
        return await self._extractor.fetch_full_text(record)
