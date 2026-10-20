"""The contract suite for extractors.

Subclass :class:`ExtractorContract` in a test module under a name pytest
collects, such as ``TestMyExtractor``, and give it a ``make_extractor``
fixture. Serve the listing from a stub, such as an ``httpx.MockTransport``, so
the suite runs offline:

```python
import httpx
import pytest

from sci_etl_core.testing import ExtractorContract

from my_package import MyExtractor
from my_tests.stubs import serve_listing


class TestMyExtractor(ExtractorContract):
    @pytest.fixture
    def make_extractor(self):
        return lambda: MyExtractor(httpx.AsyncClient(transport=httpx.MockTransport(serve_listing)))
```

The tests are plain functions that run each scenario with :func:`asyncio.run`,
so pytest-asyncio is not needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ClassVar

import pytest

from sci_etl_core.exceptions import UpstreamError
from sci_etl_core.extractors.async_base import AsyncExtractor, OffsetListing
from sci_etl_core.models import ListingPage, RawRecord


def _ids(page: ListingPage) -> list[str]:
    return [record.record_id for record in page.records]


def _check_page(page: ListingPage) -> None:
    assert isinstance(page, ListingPage), f"fetch_page returned {type(page).__name__}, not a ListingPage"
    assert all(isinstance(record, RawRecord) for record in page.records), "a page record is not a RawRecord"
    assert page.entries >= len(page.records), "entries counts fewer entries than the page has records"
    assert not page.truncated or page.next_cursor is None, "a truncated page has a next cursor"


class ExtractorContract:
    """Tests every :class:`~sci_etl_core.extractors.async_base.AsyncExtractor` must pass.

    A subclass provides the ``make_extractor`` fixture. It returns a callable
    that takes no argument and returns a new extractor over the same listing
    each time it is called, as each run of a pipeline would build it. The
    suite calls it inside a running event loop. The listing must be offline,
    must answer the same request the same way every time, must hold at least
    two pages of :attr:`page_size` entries for :attr:`query`, and must end
    within :attr:`max_pages` pages.

    A subclass may also override the ``make_unavailable_extractor`` fixture
    to check that an unreachable source raises
    :class:`~sci_etl_core.exceptions.UpstreamError` rather than returning an
    empty page.

    Some tests check an optional capability and skip when the implementation
    lacks it: the offset test, when the extractor is not an
    :class:`~sci_etl_core.extractors.async_base.OffsetListing`, and the
    unavailable-source test, when ``make_unavailable_extractor`` returns
    ``None``.
    """

    query: ClassVar[str] = "contract"
    """The query every test lists."""

    page_size: ClassVar[int] = 2
    """The page size every test asks for."""

    max_pages: ClassVar[int] = 50
    """The most pages the listing may take to end."""

    @pytest.fixture
    def make_unavailable_extractor(self) -> Callable[[], AsyncExtractor] | None:
        """Return a callable that builds an extractor whose source fails every request, or ``None``.

        The source answers every request with a server-side failure, such as
        status ``503``, and the extractor must not wait between retries. The
        default returns ``None``, which skips the unavailable-source test.
        """
        return None

    def test_the_first_page_is_a_listing_page(self, make_extractor: Callable[[], AsyncExtractor]) -> None:
        """``cursor=None`` returns a well-formed first page with records and a next cursor."""

        async def scenario() -> None:
            page = await make_extractor().fetch_page(self.query, None, self.page_size)
            _check_page(page)
            assert page.records, "the first page has no records"
            assert page.next_cursor is not None, "the listing must have a second page"

        asyncio.run(scenario())

    def test_a_cursor_resumes_in_a_new_extractor(self, make_extractor: Callable[[], AsyncExtractor]) -> None:
        """A next cursor returns the same page again, and from a new extractor, as a resumed run asks for it."""

        async def scenario() -> None:
            extractor = make_extractor()
            first = await extractor.fetch_page(self.query, None, self.page_size)
            assert first.next_cursor is not None, "the listing must have a second page"
            second = await extractor.fetch_page(self.query, first.next_cursor, self.page_size)
            again = await extractor.fetch_page(self.query, first.next_cursor, self.page_size)
            resumed = await make_extractor().fetch_page(self.query, first.next_cursor, self.page_size)
            _check_page(second)
            assert _ids(second) != _ids(first)
            assert _ids(again) == _ids(second)
            assert _ids(resumed) == _ids(second)
            assert resumed.next_cursor == second.next_cursor

        asyncio.run(scenario())

    def test_the_listing_ends(self, make_extractor: Callable[[], AsyncExtractor]) -> None:
        """Following next cursors reaches a page without one, and every page is well formed."""

        async def scenario() -> None:
            extractor = make_extractor()
            page = await extractor.fetch_page(self.query, None, self.page_size)
            pages = 1
            _check_page(page)
            while page.next_cursor is not None and pages < self.max_pages:
                page = await extractor.fetch_page(self.query, page.next_cursor, self.page_size)
                pages += 1
                _check_page(page)
            assert page.next_cursor is None, f"the listing did not end within {self.max_pages} pages"

        asyncio.run(scenario())

    def test_offset_cursors_match_the_listing(self, make_extractor: Callable[[], AsyncExtractor]) -> None:
        """For an ``OffsetListing``, offset 0 is the first page and the next page's offset is its next page."""

        async def scenario() -> None:
            extractor = make_extractor()
            if not isinstance(extractor, OffsetListing):
                pytest.skip(f"{type(extractor).__name__} is not an OffsetListing")
            first = await extractor.fetch_page(self.query, None, self.page_size)
            assert first.next_cursor is not None, "the listing must have a second page"
            at_zero = await extractor.fetch_page(self.query, extractor.cursor_for_offset(0), self.page_size)
            second = await extractor.fetch_page(self.query, first.next_cursor, self.page_size)
            by_offset = await extractor.fetch_page(
                self.query, extractor.cursor_for_offset(first.entries), self.page_size
            )
            assert _ids(at_zero) == _ids(first)
            assert _ids(by_offset) == _ids(second)

        asyncio.run(scenario())

    def test_full_text_is_text(self, make_extractor: Callable[[], AsyncExtractor]) -> None:
        """``fetch_full_text`` returns a string for a listed record."""

        async def scenario() -> None:
            extractor = make_extractor()
            page = await extractor.fetch_page(self.query, None, self.page_size)
            assert page.records, "the first page has no records"
            assert isinstance(await extractor.fetch_full_text(page.records[0]), str)

        asyncio.run(scenario())

    def test_an_unavailable_source_raises_upstream_error(
        self, make_unavailable_extractor: Callable[[], AsyncExtractor] | None
    ) -> None:
        """A source that fails every request raises ``UpstreamError`` instead of returning an empty page."""
        if make_unavailable_extractor is None:
            pytest.skip("make_unavailable_extractor is not provided")

        async def scenario() -> None:
            with pytest.raises(UpstreamError):
                await make_unavailable_extractor().fetch_page(self.query, None, self.page_size)

        asyncio.run(scenario())
