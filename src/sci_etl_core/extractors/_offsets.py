from __future__ import annotations

from sci_etl_core.exceptions import StaleCursorError
from sci_etl_core.models import ListingPage, RawRecord


def decimal_cursor(offset: int) -> str:
    """Return ``offset`` as a decimal cursor.

    Raises:
        ValueError: ``offset`` is negative.
    """
    if offset < 0:
        raise ValueError("A listing offset must not be negative")
    return str(offset)


def offset_from_cursor(cursor: str | None) -> int:
    """Return the listing offset a decimal cursor names; ``None`` is offset 0.

    Raises:
        StaleCursorError: ``cursor`` is not a decimal offset, for example one
            saved while the listing was paged another way.
    """
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdecimal():
        raise StaleCursorError(f"Cursor {cursor!r} is not a listing offset")
    return int(cursor)


def offset_page(records: list[RawRecord], entries: int, offset: int) -> ListingPage:
    """Build the page at ``offset`` of a listing that pages by offset.

    The listing continues at ``offset + entries`` until a page has no entries.
    """
    return ListingPage(
        records=tuple(records),
        entries=entries,
        next_cursor=decimal_cursor(offset + entries) if entries else None,
    )
