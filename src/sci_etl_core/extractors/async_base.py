from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from sci_etl_core.models import ListingPage, RawRecord


class AsyncExtractor(ABC):
    """Contract for a paged source of scientific records.

    :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` calls
    :meth:`fetch_page` once per page and never concurrently, and
    :meth:`fetch_full_text` concurrently for the relevant records of that
    page. The pipeline skips records it has already processed, so an
    extractor returns every entry it can read.
    """

    @abstractmethod
    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        """Fetch and parse one page; ``cursor=None`` is the first page.

        ``cursor`` is a ``next_cursor`` an earlier page returned, possibly in
        an earlier run. ``page_size`` is how many entries to ask for; a source
        may return fewer.

        Raises:
            UpstreamError: The source could not be reached or answered with a
                server-side failure. Implementations must not collapse this
                into an empty page.
            MalformedResponseError: The payload could not be interpreted.
            StaleCursorError: The source no longer accepts ``cursor``.
            ExtractionError: The source rejected the request permanently.
        """

    @abstractmethod
    async def fetch_full_text(self, record: RawRecord) -> str:
        """Retrieve the best-available full text for a record."""


@runtime_checkable
class OffsetListing(Protocol):
    """An extractor whose cursors are decimal offsets into the listing.

    ``newest_first`` runs and ``run(start_index=)`` need it. The cursor for
    offset 0 is the first page, the same as ``None``.
    """

    def cursor_for_offset(self, offset: int) -> str:
        """Return the cursor of the listing page that starts at ``offset``."""
        ...

