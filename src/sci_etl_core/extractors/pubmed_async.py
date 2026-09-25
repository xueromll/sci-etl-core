from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from lxml import etree

from sci_etl_core._deprecation import warn_logger_argument
from sci_etl_core.exceptions import MalformedResponseError, ParsingError
from sci_etl_core.extractors._http import RetryingFetcher, parse_document
from sci_etl_core.extractors._offsets import decimal_cursor, offset_from_cursor
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import ListingPage, RawRecord
from sci_etl_core.parsers._xml import local_name, parse_untrusted_xml
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.jats import JatsXmlParser
from sci_etl_core.rate_limiter import RateLimiting

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_MAX_RESULTS = 9_999
_WHITESPACE = re.compile(r"\s+")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class AsyncPubMedExtractor(AsyncExtractor):
    """Page through PubMed search results through NCBI's E-utilities, newest first by default.

    ``query`` is a PubMed search term, with the same syntax as the PubMed
    website. Its cursors are decimal offsets, so it is an
    :class:`~sci_etl_core.extractors.async_base.OffsetListing`. Each listing
    page costs two requests: ``esearch`` for the ids and
    ``efetch`` for their records. NCBI allows 3 requests per second without an
    ``api_key`` and 10 with one; pass a ``rate_limiter`` that stays under that,
    and identify your project with ``tool`` and ``email``.

    Each record's ``record_id`` is its PMID, and its ``metadata`` holds
    ``authors``, ``categories`` (MeSH headings), ``published``, ``year``,
    ``journal``, and ``doi`` and ``pmcid`` when known.

    Full text is read from PubMed Central for a record with a PMC id, parsed
    as JATS, and falls back to the abstract when PMC has no body for it. The
    injected ``client`` is borrowed and never closed.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str | None = None,
        tool: str | None = None,
        email: str | None = None,
        sort: str | None = "pub_date",
        full_text_parser: Parser | None = None,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        max_retry_after: float = 60.0,
        sleep: Any = asyncio.sleep,
        logger: Callable[[str], None] | None = None,
        rate_limiter: RateLimiting | None = None,
    ) -> None:
        """Configure the extractor.

        ``full_text_parser`` reads PubMed Central's full text and defaults to
        :class:`~sci_etl_core.parsers.jats.JatsXmlParser`. E-utilities only
        pages through the first 9,999 results of a search, so the listing is
        ``truncated`` there.

        .. deprecated:: 0.5.0
            ``logger`` emits a :class:`DeprecationWarning`; 0.6.0 logs through
            the standard :mod:`logging` module instead.

        Raises:
            ValueError: ``max_retries`` is less than 1 or ``max_retry_after`` is
                negative.
        """
        warn_logger_argument("AsyncPubMedExtractor", logger)
        self._log = logger or (lambda _msg: None)
        self._fetcher = RetryingFetcher(
            client,
            "PubMed",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            max_retry_after=max_retry_after,
            sleep=sleep,
            logger=self._log,
            rate_limiter=rate_limiter,
        )
        identity = {"api_key": api_key, "tool": tool, "email": email}
        self._common = {name: value for name, value in identity.items() if value}
        self._sort = sort
        self._full_text_parser = full_text_parser or JatsXmlParser()

    def cursor_for_offset(self, offset: int) -> str:
        """Return the decimal cursor of the listing page at ``offset``."""
        return decimal_cursor(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        """Fetch the records at the cursor's offset: ``esearch`` for their ids, then ``efetch`` for the records.

        The page's ``entries`` is the number of ids the search returned, so a
        record PubMed no longer serves still counts toward paging. The listing
        ends on the page that reaches the search's result count. E-utilities
        only serves the first 9,999 results of a search, so a page that
        reaches that cap, or a cursor past it, is ``truncated`` and ends the
        listing.

        Raises:
            UpstreamError: Every attempt failed transiently.
            ExtractionError: NCBI rejected the request.
            MalformedResponseError: The ``esearch`` or ``efetch`` response
                could not be read.
            StaleCursorError: ``cursor`` is not a decimal offset.
        """
        offset = offset_from_cursor(cursor)
        if offset >= _MAX_RESULTS:
            self._log(f"PubMed only pages through the first {_MAX_RESULTS:,} results; offset {offset} is past them")
            return ListingPage(records=(), entries=0, next_cursor=None, truncated=True)
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retstart": offset,
            "retmax": min(max(1, page_size), _MAX_RESULTS - offset),
            "retmode": "json",
            **self._common,
        }
        if self._sort:
            params["sort"] = self._sort
        ids, count = self._search_ids(await self._fetcher.fetch(f"{_EUTILS}/esearch.fcgi", "search", params))
        if not ids:
            return ListingPage(records=(), entries=0, next_cursor=None)
        fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml", **self._common}
        records = self._records(await self._fetcher.fetch(f"{_EUTILS}/efetch.fcgi", "record fetch", fetch_params))
        end = offset + len(ids)
        if count is not None and end >= count:
            return ListingPage(records=records, entries=len(ids), next_cursor=None)
        if end >= _MAX_RESULTS:
            self._log(f"PubMed only pages through the first {_MAX_RESULTS:,} results; the listing stops at {end}")
            return ListingPage(records=records, entries=len(ids), next_cursor=None, truncated=True)
        return ListingPage(records=records, entries=len(ids), next_cursor=decimal_cursor(end))

    def _records(self, payload: bytes) -> tuple[RawRecord, ...]:
        try:
            root = parse_untrusted_xml(payload, "PubMed efetch response")
        except ParsingError as exc:
            raise MalformedResponseError(str(exc)) from exc
        if local_name(root) != "PubmedArticleSet":
            raise MalformedResponseError("PubMed efetch response is not a <PubmedArticleSet>")
        return tuple(record for article in root.iter("PubmedArticle") if (record := self._record(article)))

    async def fetch_full_text(self, record: RawRecord) -> str:
        """Return the PubMed Central full text, or the abstract when there is none.

        Raises:
            UpstreamError: PubMed Central could not be reached; the record is
                retried on the next run.
        """
        pmcid = record.metadata.get("pmcid")
        if not isinstance(pmcid, str) or not pmcid:
            return record.abstract
        params = {"db": "pmc", "id": pmcid.removeprefix("PMC"), "retmode": "xml", **self._common}
        content = await self._fetcher.fetch_optional(
            f"{_EUTILS}/efetch.fcgi", f"full-text fetch for {record.record_id!r}", params
        )
        if content is None:
            return record.abstract
        if isinstance(self._full_text_parser, JatsXmlParser):
            return await self._jats_full_text(self._full_text_parser, content, record)
        text = await parse_document(self._full_text_parser, content, "PMC full text", record, self._log)
        return text or record.abstract

    async def _jats_full_text(self, parser: JatsXmlParser, content: bytes, record: RawRecord) -> str:
        try:
            article = await asyncio.to_thread(parser.parse_article, content)
        except ParsingError as exc:
            self._log(f"PMC full text unusable for {record.record_id!r}: {exc}")
            return record.abstract
        if not article.sections:
            self._log(f"PMC has no full text for {record.record_id!r}")
            return record.abstract
        blocks = [article.title or record.title, article.abstract or record.abstract, article.body_text()]
        return "\n\n".join(block for block in blocks if block)

    @staticmethod
    def _search_ids(payload: bytes) -> tuple[list[str], int | None]:
        try:
            result = json.loads(payload)["esearchresult"]
            ids = result["idlist"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MalformedResponseError("PubMed esearch response has no id list") from exc
        if not isinstance(ids, list):
            raise MalformedResponseError("PubMed esearch id list is not a list")
        count = result.get("count")
        total = int(count) if isinstance(count, str) and count.isascii() and count.isdecimal() else None
        return [str(value) for value in ids if str(value).strip()], total

    def _record(self, article: etree._Element) -> RawRecord | None:
        citation = article.find("MedlineCitation")
        pmid = _text(citation.find("PMID")) if citation is not None else ""
        if citation is None or not pmid:
            return None
        details = citation.find("Article")
        title = _text(details.find("ArticleTitle")) if details is not None else ""
        abstract_parts = [] if details is None else [
            _labelled(part) for part in details.findall("Abstract/AbstractText") if _text(part)
        ]
        return RawRecord(
            record_id=pmid,
            title=title,
            abstract="\n".join(abstract_parts),
            source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            metadata=self._metadata(article, citation, details),
        )

    @staticmethod
    def _metadata(
        article: etree._Element, citation: etree._Element, details: etree._Element | None
    ) -> dict[str, Any]:
        authors: list[str] = []
        journal = ""
        published = None
        if details is not None:
            for author in details.findall("AuthorList/Author"):
                parts = (_text(author.find("ForeName")), _text(author.find("LastName")))
                name = " ".join(part for part in parts if part) or _text(author.find("CollectiveName"))
                if name:
                    authors.append(name)
            journal = _text(details.find("Journal/Title"))
            published = _article_date(details)
        metadata: dict[str, Any] = {
            "authors": authors,
            "categories": [
                heading
                for heading in map(_text, citation.findall("MeshHeadingList/MeshHeading/DescriptorName"))
                if heading
            ],
        }
        if published:
            metadata["published"] = published
            metadata["year"] = published[:4]
        if journal:
            metadata["journal"] = journal
        for article_id in article.findall("PubmedData/ArticleIdList/ArticleId"):
            kind = article_id.get("IdType")
            value = _text(article_id)
            if kind in {"doi", "pmc"} and value:
                metadata.setdefault("doi" if kind == "doi" else "pmcid", value)
        return metadata


def _text(element: etree._Element | None) -> str:
    if element is None:
        return ""
    return _WHITESPACE.sub(" ", "".join(element.itertext())).strip()


def _labelled(part: etree._Element) -> str:
    label = part.get("Label")
    text = _text(part)
    return f"{label}: {text}" if label else text


def _article_date(details: etree._Element) -> str | None:
    electronic = details.find("ArticleDate")
    if electronic is not None:
        date = _date(electronic)
        if date:
            return date
    issue = details.find("Journal/JournalIssue/PubDate")
    if issue is None:
        return None
    return _date(issue) or _medline_year(_text(issue.find("MedlineDate")))


def _date(node: etree._Element) -> str | None:
    year = _text(node.find("Year"))
    if not (len(year) == 4 and year.isdigit()):
        return None
    month_text = _text(node.find("Month"))
    month = int(month_text) if month_text.isdigit() else _month_number(month_text)
    if month is None or not 1 <= month <= 12:
        return year
    day = _text(node.find("Day"))
    if day.isdigit() and 1 <= int(day) <= 31:
        return f"{year}-{month:02d}-{int(day):02d}"
    return f"{year}-{month:02d}"


def _month_number(text: str) -> int | None:
    abbreviation = text[:3].casefold()
    return _MONTHS.index(abbreviation) + 1 if abbreviation in _MONTHS else None


def _medline_year(text: str) -> str | None:
    match = re.match(r"(\d{4})", text)
    return match.group(1) if match else None
