from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

from sci_etl_core._deprecation import warn_logger_argument
from sci_etl_core.exceptions import ExtractionError, MalformedResponseError, StaleCursorError
from sci_etl_core.extractors._http import RetryingFetcher, parse_document
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import ListingPage, RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.reference_trimmer import trim_after_references
from sci_etl_core.rate_limiter import RateLimiting

_ID_PREFIX = "https://openalex.org/"
_MAX_PER_PAGE = 200
_BAD_REQUEST = 400


def reconstruct_abstract(inverted_index: Any) -> str:
    """Rebuild an abstract from OpenAlex's ``abstract_inverted_index``, which maps each word to its positions."""
    if not isinstance(inverted_index, dict):
        return ""
    positioned: dict[int, str] = {}
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and not isinstance(position, bool) and position >= 0:
                positioned[position] = str(word)
    return " ".join(positioned[position] for position in sorted(positioned))


def _short_id(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    return text[len(_ID_PREFIX):] if text.startswith(_ID_PREFIX) else text


class AsyncOpenAlexExtractor(AsyncExtractor):
    """Page through OpenAlex works matching a search, newest first by default.

    ``query`` is OpenAlex's full-text ``search``; ``filter`` narrows it with
    OpenAlex filter syntax, such as ``"type:article,from_publication_date:2020-01-01"``.
    Pass ``mailto`` to join OpenAlex's polite pool, and ``api_key`` when you
    have one. Paging uses OpenAlex's opaque cursors, so the extractor is not an
    :class:`~sci_etl_core.extractors.async_base.OffsetListing` and does not
    support ``newest_first`` runs; a finished listing starts again from its
    first page on the next run, skipping processed works by id.

    Each record's ``record_id`` is the OpenAlex work id, such as
    ``"W2741809807"``, and its ``metadata`` holds ``authors``, ``categories``
    (the work's topics), ``published``, ``year``, ``doi``, ``venue``, and
    ``references``, the ids of the works it cites, when OpenAlex has them.

    Full text comes from the PDF of the best open-access location when a
    ``pdf_parser`` is given, and the abstract otherwise. The injected
    ``client`` is borrowed and never closed.
    """

    API_URL = "https://api.openalex.org/works"

    def __init__(
        self,
        client: httpx.AsyncClient,
        pdf_parser: Parser | None = None,
        *,
        filter: str | None = None,
        sort: str | None = "publication_date:desc",
        mailto: str | None = None,
        api_key: str | None = None,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        max_retry_after: float = 60.0,
        sleep: Any = asyncio.sleep,
        logger: Callable[[str], None] | None = None,
        rate_limiter: RateLimiting | None = None,
        max_download_bytes: int | None = None,
    ) -> None:
        """Configure the extractor.

        OpenAlex serves at most 200 works per page, so a page asks for at most
        200.

        .. deprecated:: 0.5.0
            ``logger`` emits a :class:`PendingDeprecationWarning`; 0.6.0 logs through
            the standard :mod:`logging` module instead.

        With ``max_download_bytes``, a response body is read only up to that
        many bytes, so a huge response cannot exhaust memory. A larger listing
        page raises :class:`~sci_etl_core.exceptions.ExtractionError`; a larger
        full-text download is logged and passed over like an unavailable one.

        Raises:
            ValueError: ``max_retries`` is less than 1, ``max_retry_after`` is
                negative, or ``max_download_bytes`` is less than 1.
        """
        warn_logger_argument("AsyncOpenAlexExtractor", logger)
        self._log = logger or (lambda _msg: None)
        self._fetcher = RetryingFetcher(
            client,
            "OpenAlex",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            max_retry_after=max_retry_after,
            sleep=sleep,
            logger=self._log,
            rate_limiter=rate_limiter,
            max_bytes=max_download_bytes,
        )
        self._pdf_parser = pdf_parser
        self._filter = filter
        self._sort = sort
        self._mailto = mailto
        self._api_key = api_key

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        """Fetch one page of works through OpenAlex's cursor paging, skipping works without an id.

        ``cursor=None`` asks for the first page (``cursor=*``), and the page's
        ``next_cursor`` is the ``meta.next_cursor`` OpenAlex returned, so paging
        is not limited to the first 10,000 results. A page asks for at most
        200 works. The listing ends on a page without works or without a next
        cursor.

        Raises:
            UpstreamError: Every attempt failed transiently.
            StaleCursorError: OpenAlex rejected ``cursor`` as invalid, or
                ``cursor`` is a decimal listing offset, as sci-etl-core 0.4
                saved.
            ExtractionError: OpenAlex rejected the request, for example for an
                invalid filter.
            MalformedResponseError: The payload is not JSON with a ``results``
                list.
        """
        if cursor is not None and cursor.isascii() and cursor.isdecimal():
            raise StaleCursorError(f"OpenAlex cursor {cursor!r} is a listing offset, not an OpenAlex cursor")
        params: dict[str, Any] = {"per-page": max(1, min(page_size, _MAX_PER_PAGE)), "cursor": cursor or "*"}
        if query:
            params["search"] = query
        options = {"filter": self._filter, "sort": self._sort, "mailto": self._mailto, "api_key": self._api_key}
        params.update({name: value for name, value in options.items() if value})
        response = await self._fetcher.response(self.API_URL, "search", params)
        if not response.is_success:
            if cursor is not None and response.status_code == _BAD_REQUEST and b"cursor" in response.content.lower():
                raise StaleCursorError(f"OpenAlex no longer accepts cursor {cursor!r}")
            raise ExtractionError(f"OpenAlex rejected the search with status {response.status_code}")
        listing = self._decode(response.content)
        results = listing.get("results")
        if not isinstance(results, list):
            raise MalformedResponseError("OpenAlex listing has no results list")
        meta = listing.get("meta")
        next_cursor = meta.get("next_cursor") if isinstance(meta, dict) else None
        records = tuple(record for work in results if (record := self._record(work)) is not None)
        if not results or not isinstance(next_cursor, str) or not next_cursor:
            next_cursor = None
        return ListingPage(records=records, entries=len(results), next_cursor=next_cursor)

    def _record(self, work: Any) -> RawRecord | None:
        if not isinstance(work, dict):
            return None
        record_id = _short_id(work.get("id"))
        if not record_id:
            return None
        return RawRecord(
            record_id=record_id,
            title=str(work.get("display_name") or work.get("title") or ""),
            abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
            source_url=self._landing_page(work),
            metadata=self._metadata(work),
        )

    async def fetch_full_text(self, record: RawRecord) -> str:
        """Return the open-access PDF's text, or the abstract when there is no usable PDF.

        Raises:
            UpstreamError: The PDF download failed transiently; the record is
                retried on the next run rather than settled on its abstract.
        """
        pdf_url = record.metadata.get("pdf_url")
        if self._pdf_parser is None or not isinstance(pdf_url, str) or not pdf_url:
            return record.abstract
        content = await self._fetcher.fetch_optional(pdf_url, f"PDF download for {record.record_id!r}")
        if content is None:
            return record.abstract
        text = await parse_document(self._pdf_parser, content, "PDF", record, self._log)
        return (trim_after_references(text) or text) if text else record.abstract

    @staticmethod
    def _decode(payload: bytes) -> dict[str, Any]:
        try:
            decoded = json.loads(payload)
        except ValueError as exc:
            raise MalformedResponseError("OpenAlex response is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise MalformedResponseError("OpenAlex response is not a JSON object")
        return decoded

    @staticmethod
    def _landing_page(work: dict[str, Any]) -> str | None:
        doi = work.get("doi")
        if isinstance(doi, str) and doi:
            return doi
        location = work.get("primary_location")
        if isinstance(location, dict) and isinstance(location.get("landing_page_url"), str):
            return str(location["landing_page_url"])
        return None

    @staticmethod
    def _metadata(work: dict[str, Any]) -> dict[str, Any]:
        authors = [
            name
            for authorship in work.get("authorships") or []
            if isinstance(authorship, dict)
            and isinstance(authorship.get("author"), dict)
            and (name := str(authorship["author"].get("display_name") or "").strip())
        ]
        topics = [
            name
            for topic in work.get("topics") or []
            if isinstance(topic, dict) and (name := str(topic.get("display_name") or "").strip())
        ]
        metadata: dict[str, Any] = {"authors": authors, "categories": topics}
        published = work.get("publication_date")
        if isinstance(published, str) and published:
            metadata["published"] = published
        year = work.get("publication_year")
        if isinstance(year, int) and not isinstance(year, bool):
            metadata["year"] = str(year)
        doi = work.get("doi")
        if isinstance(doi, str) and doi:
            metadata["doi"] = doi.removeprefix("https://doi.org/")
        location = work.get("primary_location")
        source = location.get("source") if isinstance(location, dict) else None
        if isinstance(source, dict) and source.get("display_name"):
            metadata["venue"] = str(source["display_name"])
        references = [_short_id(work_id) for work_id in work.get("referenced_works") or [] if _short_id(work_id)]
        if references:
            metadata["references"] = references
        best = work.get("best_oa_location")
        if isinstance(best, dict) and isinstance(best.get("pdf_url"), str) and best["pdf_url"]:
            metadata["pdf_url"] = best["pdf_url"]
        return metadata
