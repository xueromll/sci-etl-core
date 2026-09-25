"""Page a mocked extractor through its ``search`` and ``parse_listing`` mocks.

Pipeline tests written against the 0.4 extractor contract keep their
``search`` and ``parse_listing`` mocks; :func:`page_through_search` gives the
mock the 0.5 ``fetch_page`` and ``cursor_for_offset`` on top of them, with the
paging rules of :class:`~sci_etl_core.extractors._legacy.LegacyExtractorAdapter`.
"""

from __future__ import annotations

from typing import Any

from sci_etl_core.exceptions import UpstreamError
from sci_etl_core.models import ListingPage


def page_through_search(mocker: Any, extractor: Any) -> Any:
    async def fetch_page(query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = int(cursor or 0)
        raw_listing = await extractor.search(query, page_size, offset)
        if not raw_listing:
            raise UpstreamError("Listing fetch returned no payload")
        records, entries = extractor.parse_listing(raw_listing, set())
        next_cursor = str(offset + entries) if entries else None
        return ListingPage(records=tuple(records), entries=entries, next_cursor=next_cursor)

    extractor.fetch_page = mocker.AsyncMock(side_effect=fetch_page)
    extractor.cursor_for_offset = str
    return extractor
