from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

import httpx
from lxml import etree

from sci_etl_core.exceptions import MalformedResponseError, ParsingError
from sci_etl_core.extractors._http import RetryingFetcher, parse_document
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers._xml import local_name, parse_untrusted_xml
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.jats import JatsXmlParser
from sci_etl_core.rate_limiter import RateLimiting

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_MAX_RETMAX = 10_000
_MAX_RETSTART = 9_999
_XML_PREAMBLE = re.compile(rb"^\s*(<\?xml[^>]*\?>)?\s*(<!DOCTYPE[^>]*>)?\s*", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class AsyncPubMedExtractor(AsyncExtractor):
    """Page through PubMed search results through NCBI's E-utilities, newest first by default.

    ``query`` is a PubMed search term, with the same syntax as the PubMed
    website. Each listing page costs two requests: ``esearch`` for the ids and
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
        pages through the first 10,000 results of a search, so ``search``
        returns an empty listing beyond them.

        Raises:
            ValueError: ``max_retries`` is less than 1 or ``max_retry_after`` is
                negative.
        """
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

    async def search(self, query: str, max_results: int, start_index: int) -> bytes:
        """Fetch the records at offsets ``start_index`` to ``start_index + max_results``.

        The page is returned as a ``<pubmed-listing>`` element whose
        ``entries`` attribute is the number of ids the search returned, wrapped
        around the ``efetch`` response, so a record PubMed no longer serves
        still counts toward paging.

        Raises:
            UpstreamError: Every attempt failed transiently.
            ExtractionError: NCBI rejected the request.
            MalformedResponseError: The ``esearch`` response could not be read.
        """
        if start_index > _MAX_RETSTART:
            self._log(f"PubMed only pages through the first 10,000 results; offset {start_index} is past them")
            return b'<pubmed-listing entries="0"/>'
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retstart": start_index,
            "retmax": min(max(1, max_results), _MAX_RETMAX - start_index),
            "retmode": "json",
            **self._common,
        }
        if self._sort:
            params["sort"] = self._sort
        ids = self._search_ids(await self._fetcher.fetch(f"{_EUTILS}/esearch.fcgi", "search", params))
        if not ids:
            return b'<pubmed-listing entries="0"/>'
        fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml", **self._common}
        records = await self._fetcher.fetch(f"{_EUTILS}/efetch.fcgi", "record fetch", fetch_params)
        body = _XML_PREAMBLE.sub(b"", records, count=1)
        return b'<pubmed-listing entries="' + str(len(ids)).encode() + b'">' + body + b"</pubmed-listing>"

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse a page returned by :meth:`search`.

        Raises:
            MalformedResponseError: The payload is not a ``<pubmed-listing>``.
        """
        try:
            root = parse_untrusted_xml(raw_listing, "PubMed listing")
        except ParsingError as exc:
            raise MalformedResponseError(str(exc)) from exc
        entries = root.get("entries", "")
        if local_name(root) != "pubmed-listing" or not entries.isdigit():
            raise MalformedResponseError("PubMed listing payload is not a <pubmed-listing>")
        records: list[RawRecord] = []
        for article in root.iter("PubmedArticle"):
            record = self._record(article)
            if record is not None and record.record_id not in seen_ids:
                records.append(record)
        return records, int(entries)

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
    def _search_ids(payload: bytes) -> list[str]:
        try:
            decoded = json.loads(payload)
            ids = decoded["esearchresult"]["idlist"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MalformedResponseError("PubMed esearch response has no id list") from exc
        if not isinstance(ids, list):
            raise MalformedResponseError("PubMed esearch id list is not a list")
        return [str(value) for value in ids if str(value).strip()]

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
