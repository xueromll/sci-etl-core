from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx

from sci_etl_core.exceptions import MalformedResponseError
from sci_etl_core.extractors._http import RetryingFetcher, parse_document
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.reference_trimmer import trim_after_references
from sci_etl_core.rate_limiter import RateLimiting

_ID_PREFIX = "https://openalex.org/"
_MAX_PER_PAGE = 200


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
    have one.

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
    ) -> None:
        """Configure the extractor.

        OpenAlex pages at most 200 works and only the first 10,000 results of
        a search through page numbers, so ``search`` asks for at most 200 at a
        time and returns an empty listing beyond 10,000.

        Raises:
            ValueError: ``max_retries`` is less than 1 or ``max_retry_after`` is
                negative.
        """
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
        )
        self._pdf_parser = pdf_parser
        self._filter = filter
        self._sort = sort
        self._mailto = mailto
        self._api_key = api_key

    async def search(self, query: str, max_results: int, start_index: int) -> bytes:
        """Fetch the works at offsets ``start_index`` to ``start_index + max_results``.

        OpenAlex pages by page number, so the page holding ``start_index`` is
        requested and the works before ``start_index`` on it are dropped.

        Raises:
            UpstreamError: Every attempt failed transiently.
            ExtractionError: OpenAlex rejected the request, for example for an
                invalid filter.
        """
        per_page = max(1, min(max_results, _MAX_PER_PAGE))
        page = start_index // per_page + 1
        if page * per_page > 10_000:
            self._log(f"OpenAlex only pages through the first 10,000 results; offset {start_index} is past them")
            return b'{"results": []}'
        params: dict[str, Any] = {"per-page": per_page, "page": page}
        if query:
            params["search"] = query
        options = {"filter": self._filter, "sort": self._sort, "mailto": self._mailto, "api_key": self._api_key}
        params.update({name: value for name, value in options.items() if value})
        payload = await self._fetcher.fetch(self.API_URL, "search", params)
        listing = self._decode(payload)
        results = listing.get("results")
        skip = start_index - (page - 1) * per_page
        listing["results"] = results[skip:] if isinstance(results, list) else results
        return json.dumps(listing).encode("utf-8")

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse a listing page, skipping works already seen or without an id.

        Raises:
            MalformedResponseError: The payload is not JSON with a ``results`` list.
        """
        results = self._decode(raw_listing).get("results")
        if not isinstance(results, list):
            raise MalformedResponseError("OpenAlex listing has no results list")
        records: list[RawRecord] = []
        for work in results:
            if not isinstance(work, dict):
                continue
            record_id = _short_id(work.get("id"))
            if not record_id or record_id in seen_ids:
                continue
            records.append(
                RawRecord(
                    record_id=record_id,
                    title=str(work.get("display_name") or work.get("title") or ""),
                    abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
                    source_url=self._landing_page(work),
                    metadata=self._metadata(work),
                )
            )
        return records, len(results)

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
