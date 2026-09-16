from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from sci_etl_core.exceptions import ParsingError
from sci_etl_core.parsers._xml import local_name, parse_untrusted_xml
from sci_etl_core.parsers.base import Parser

_WHITESPACE = re.compile(r"\s+")
_BLOCK_ELEMENTS = frozenset(
    {"p", "title", "caption", "list", "list-item", "disp-quote", "def", "term", "table-wrap", "fig", "sec"}
    | {"boxed-text"}
)
_SKIPPED_IN_TEXT = frozenset({"fn-group", "ref-list", "graphic", "media", "object-id", "label", "table-wrap-foot"})
_TABLE_CONTENT = frozenset({"table"})
_CITATIONS = frozenset({"mixed-citation", "element-citation", "citation"})
_MONTH_ABBREVIATIONS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTHS = {name: number for number, name in enumerate(_MONTH_ABBREVIATIONS, 1)}


@dataclass(frozen=True, slots=True)
class JatsSection:
    """One body section: its heading, nesting ``level`` (1 for a top-level section), and paragraph text."""

    title: str
    level: int
    text: str


@dataclass(frozen=True, slots=True)
class JatsArticle:
    """The parts of a JATS article that text mining uses.

    ``published`` is an ISO 8601 date of the earliest ``<pub-date>`` given, as
    precise as the source: ``"2024"``, ``"2024-03"``, or ``"2024-03-07"``.
    ``identifiers`` maps each ``<article-id>`` type, such as ``doi``,
    ``pmid``, or ``pmcid``, to its value. ``references`` holds the text of each
    reference in the reference list, in order.
    """

    title: str
    abstract: str
    sections: tuple[JatsSection, ...] = ()
    authors: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    journal: str = ""
    published: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    references: tuple[str, ...] = ()

    @property
    def doi(self) -> str | None:
        return self.identifiers.get("doi")

    def body_text(self) -> str:
        """Return the section headings and text in document order, separated by blank lines."""
        blocks: list[str] = []
        for section in self.sections:
            if section.title:
                blocks.append(section.title)
            if section.text:
                blocks.append(section.text)
        return "\n\n".join(blocks)


class JatsXmlParser(Parser):
    """Parse JATS XML, the format of PubMed Central and many publishers' full texts.

    :meth:`parse_article` returns a :class:`JatsArticle`. :meth:`extract_text`
    returns the title, abstract, and body with section headings, leaving out
    the reference list, footnotes, and graphics, so no reference trimming is
    needed. Table cells are kept, one row per line with cells joined by tabs,
    unless ``include_tables`` is false; captions are always kept.

    An ``<article>`` may be the document root or wrapped, as in a PubMed
    Central ``<pmc-articleset>``; the first one is read. Namespaces are
    ignored. The XML is parsed without resolving entities, loading DTDs, or
    using the network.
    """

    def __init__(self, include_tables: bool = True) -> None:
        self._include_tables = include_tables

    def extract_text(self, content: bytes) -> str:
        """Return the article's title, abstract, and body as text.

        Raises:
            ParsingError: The bytes are not well-formed XML or hold no ``<article>``.
        """
        article = self.parse_article(content)
        blocks = [article.title, article.abstract, article.body_text()]
        return "\n\n".join(block for block in blocks if block)

    def parse_article(self, content: bytes) -> JatsArticle:
        """Return the first article in ``content``.

        Raises:
            ParsingError: The bytes are not well-formed XML or hold no ``<article>``.
        """
        root = parse_untrusted_xml(content, "JATS payload")
        article = root if local_name(root) == "article" else _first(root, "article")
        if article is None:
            raise ParsingError("JATS payload holds no <article>")
        meta = _first(article, "article-meta")
        journal_meta = _first(article, "journal-meta")
        body = _first(article, "body")
        back = _first(article, "back")
        return JatsArticle(
            title=self._inline(_first(meta, "article-title")),
            abstract=self._abstract(meta),
            sections=tuple(self._sections(body)),
            authors=tuple(self._authors(meta)),
            keywords=tuple(text for text in (self._inline(keyword) for keyword in _all(meta, "kwd")) if text),
            journal=self._inline(_first(journal_meta, "journal-title")),
            published=self._published(meta),
            identifiers=self._identifiers(meta),
            references=tuple(self._references(back)),
        )

    def _abstract(self, meta: etree._Element | None) -> str:
        abstracts = _all(meta, "abstract")
        chosen = next(
            (element for element in abstracts if element.get("abstract-type") in (None, "abstract", "summary")),
            abstracts[0] if abstracts else None,
        )
        if chosen is None:
            return ""
        return "\n\n".join(self._blocks(chosen))

    def _sections(self, body: etree._Element | None) -> list[JatsSection]:
        if body is None:
            return []
        sections: list[JatsSection] = []
        lead = [child for child in body if local_name(child) != "sec"]
        lead_text = "\n\n".join(block for child in lead for block in self._blocks(child))
        if lead_text:
            sections.append(JatsSection("", 0, lead_text))
        for child in body:
            if local_name(child) == "sec":
                self._section(child, 1, sections)
        return sections

    def _section(self, section: etree._Element, level: int, sections: list[JatsSection]) -> None:
        title = self._inline(_child(section, "title"))
        paragraphs = [
            block
            for child in section
            if local_name(child) not in {"sec", "title"}
            for block in self._blocks(child)
        ]
        sections.append(JatsSection(title, level, "\n\n".join(paragraphs)))
        for child in section:
            if local_name(child) == "sec":
                self._section(child, level + 1, sections)

    def _blocks(self, element: etree._Element) -> list[str]:
        blocks: list[str] = []
        buffer: list[str] = []
        self._walk(element, blocks, buffer, top=True)
        _flush(buffer, blocks)
        return blocks

    def _walk(self, node: etree._Element, blocks: list[str], buffer: list[str], top: bool) -> None:
        name = local_name(node)
        if self._skipped(name):
            if not top and node.tail:
                buffer.append(node.tail)
            return
        if name == "tr":
            _flush(buffer, blocks)
            row = "\t".join(self._inline(cell) for cell in node if local_name(cell) in {"td", "th"})
            if row.strip():
                blocks.append(row)
        else:
            is_block = name in _BLOCK_ELEMENTS
            if is_block:
                _flush(buffer, blocks)
            if node.text:
                buffer.append(node.text)
            for child in node:
                self._walk(child, blocks, buffer, top=False)
            if is_block:
                _flush(buffer, blocks)
        if not top and node.tail:
            buffer.append(node.tail)

    def _skipped(self, name: str) -> bool:
        return not name or name in _SKIPPED_IN_TEXT or (name in _TABLE_CONTENT and not self._include_tables)

    def _inline(self, element: etree._Element | None) -> str:
        if element is None:
            return ""
        pieces: list[str] = []
        self._inline_pieces(element, pieces, top=True)
        return _clean("".join(pieces))

    def _inline_pieces(self, element: etree._Element, pieces: list[str], top: bool) -> None:
        if not top and self._skipped(local_name(element)):
            if element.tail:
                pieces.append(element.tail)
            return
        if element.text:
            pieces.append(element.text)
        for child in element:
            self._inline_pieces(child, pieces, top=False)
        if not top and element.tail:
            pieces.append(element.tail)

    def _authors(self, meta: etree._Element | None) -> list[str]:
        authors: list[str] = []
        for contrib in _all(meta, "contrib"):
            if contrib.get("contrib-type", "author") != "author":
                continue
            name = _first(contrib, "name")
            if name is not None:
                given = self._inline(_child(name, "given-names"))
                surname = self._inline(_child(name, "surname"))
                full = " ".join(part for part in (given, surname) if part)
            else:
                full = self._inline(_first(contrib, "collab")) or self._inline(_first(contrib, "string-name"))
            if full:
                authors.append(full)
        return authors

    def _published(self, meta: etree._Element | None) -> str | None:
        dates: list[tuple[int, int, int, str]] = []
        for pub_date in _all(meta, "pub-date"):
            year = _number(self._inline(_child(pub_date, "year")))
            if year is None:
                continue
            month = _month(self._inline(_child(pub_date, "month")))
            day = _number(self._inline(_child(pub_date, "day"))) if month is not None else None
            text = f"{year:04d}"
            if month is not None:
                text += f"-{month:02d}"
                if day is not None and 1 <= day <= 31:
                    text += f"-{day:02d}"
            dates.append((year, month or 13, day or 32, text))
        if not dates:
            return None
        return min(dates)[3]

    def _identifiers(self, meta: etree._Element | None) -> dict[str, str]:
        identifiers: dict[str, str] = {}
        for article_id in _all(meta, "article-id"):
            kind = article_id.get("pub-id-type")
            value = self._inline(article_id)
            if kind and value:
                identifiers.setdefault(kind, value)
        return identifiers

    def _references(self, back: etree._Element | None) -> list[str]:
        references: list[str] = []
        for reference in _all(back, "ref"):
            citation = next((child for child in reference if local_name(child) in _CITATIONS), None)
            text = self._citation_text(citation)
            if text:
                references.append(text)
        return references

    def _citation_text(self, citation: etree._Element | None) -> str:
        if citation is None:
            return ""
        if local_name(citation) == "mixed-citation":
            return self._inline(citation)
        return _clean(" ".join(text.strip() for text in citation.itertext() if text.strip()))


def _first(element: etree._Element | None, name: str) -> etree._Element | None:
    if element is None:
        return None
    return next((node for node in element.iter() if node is not element and local_name(node) == name), None)


def _all(element: etree._Element | None, name: str) -> list[etree._Element]:
    if element is None:
        return []
    return [node for node in element.iter() if node is not element and local_name(node) == name]


def _child(element: etree._Element, name: str) -> etree._Element | None:
    return next((child for child in element if local_name(child) == name), None)


def _flush(buffer: list[str], blocks: list[str]) -> None:
    text = _clean("".join(buffer))
    buffer.clear()
    if text:
        blocks.append(text)


def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _number(text: str) -> int | None:
    return int(text) if text.isdigit() else None


def _month(text: str) -> int | None:
    number = _number(text)
    if number is not None:
        return number if 1 <= number <= 12 else None
    return _MONTHS.get(text[:3].casefold())
