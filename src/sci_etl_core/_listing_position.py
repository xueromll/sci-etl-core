from __future__ import annotations

from collections.abc import Callable

from sci_etl_core._listing_head import NewestFirstCursor
from sci_etl_core.extractors.async_base import OffsetListing
from sci_etl_core.models import ListingPage, PipelineMetadata


def listing_ends(page: ListingPage) -> bool:
    """Whether ``page`` is the last page of its listing, for any reason."""
    return page.truncated or page.next_cursor is None or page.entries == 0


def _offset_of(cursor: str | None) -> int | None:
    if cursor is None:
        return 0
    if cursor.isascii() and cursor.isdecimal():
        return int(cursor)
    return None


class CursorPosition:
    """Where a run is in its listing, and the cursor it saves for the next run.

    The saved cursor moves only while every page of the run has settled. At
    the end of the listing, an :class:`OffsetListing` saves the offset past
    the last entry, so entries appended later are found by the next run; any
    other extractor saves ``None``, because an opaque cursor cannot resume a
    finished listing.
    """

    def __init__(self, metadata: PipelineMetadata, cursor: str | None, offsets: OffsetListing | None) -> None:
        self._metadata = metadata
        self._offsets = offsets
        self._settled = True
        self.cursor = cursor

    @property
    def offset(self) -> int | None:
        """The listing offset of :attr:`cursor`, or ``None`` when the extractor does not page by offset."""
        return None if self._offsets is None else _offset_of(self.cursor)

    def advance(self, page: ListingPage, complete: bool) -> bool:
        """Account for a page fetched at :attr:`cursor`; return whether the listing goes on."""
        self._settled = self._settled and complete
        if listing_ends(page):
            if self._settled:
                self._metadata.cursor = self._end_cursor(page)
            self._metadata.truncated = False
            return False
        self.cursor = page.next_cursor
        if self._settled:
            self._metadata.cursor = self.cursor
        return True

    def truncate(self) -> None:
        """Start the next run from the first page, because the source stopped at its cap."""
        self._metadata.cursor = None
        self._metadata.truncated = True

    def restart(self) -> None:
        """Page again from the first page, because the source rejected the cursor."""
        self._settled = True
        self.cursor = None
        self._metadata.cursor = None

    def _end_cursor(self, page: ListingPage) -> str | None:
        offset = self.offset
        if self._offsets is None or offset is None or offset + page.entries == 0:
            return None
        return self._offsets.cursor_for_offset(offset + page.entries)


class NewestFirstPosition:
    """Where a ``newest_first`` run is in an :class:`OffsetListing`; see :class:`NewestFirstCursor`."""

    def __init__(
        self, metadata: PipelineMetadata, page_size: int, offsets: OffsetListing, log: Callable[[str], None]
    ) -> None:
        self._metadata = metadata
        self._page_size = page_size
        self._offsets = offsets
        self._log = log
        self._head = NewestFirstCursor(metadata, page_size, offsets.cursor_for_offset)
        self.offset: int = 0

    @property
    def cursor(self) -> str | None:
        """The cursor of the page at :attr:`offset`; ``None`` for the first page."""
        return self._offsets.cursor_for_offset(self.offset) if self.offset else None

    def advance(self, page: ListingPage, complete: bool) -> bool:
        """Account for a page fetched at :attr:`offset`; return whether the listing goes on."""
        if page.entries == 0:
            return self._listing_ended(self.offset)
        listed_ids = [record.record_id for record in page.records if record.record_id]
        was_scanning, was_realigned = self._head.scanning, self._head.realigned
        next_offset = self._head.observe_page(self.offset, listed_ids, page.entries, complete)
        if was_scanning and not self._head.scanning:
            self._log(f"{self._head.shift} new listing entries since the last run; resuming at {next_offset}")
        if self._head.realigned and not was_realigned:
            self._log(f"Records last seen before the saved offset have moved; paging on from {next_offset}")
        if page.next_cursor is None:
            return self._listing_ended(self.offset + page.entries)
        self.offset = next_offset
        return True

    def truncate(self) -> None:
        """Start the next run's backlog from the first page, because the source stopped at its cap."""
        self._metadata.cursor = None
        self._metadata.truncated = True

    def restart(self) -> None:
        """Rescan from offset 0 and rebuild the saved head, because the source rejected the cursor."""
        self._metadata.cursor = None
        self._metadata.head_ids = []
        self._metadata.head_offset = 0
        self._metadata.tail_ids = []
        self._head = NewestFirstCursor(self._metadata, self._page_size, self._offsets.cursor_for_offset)
        self.offset = 0

    def _listing_ended(self, end: int) -> bool:
        was_scanning = self._head.scanning
        resume_at = self._head.listing_ended()
        if was_scanning:
            self._log("Listing ended before the records last seen at its head; rescanned from offset 0")
        if resume_at is None or resume_at >= end:
            self._metadata.truncated = False
            return False
        self._log(f"Records last seen before the saved offset have moved; paging on from {resume_at}")
        self.offset = resume_at
        return True
