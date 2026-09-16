from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

from sci_etl_core.exceptions import ParsingError
from sci_etl_core.parsers._xml import local_name, parse_untrusted_xml
from sci_etl_core.parsers.base import Parser

_DOCUMENT_PART = "word/document.xml"
_NOTE_PARTS = ("word/footnotes.xml", "word/endnotes.xml")
_DEFAULT_MAX_PART_BYTES = 64 * 1024 * 1024
_SKIPPED = frozenset({"del", "delText", "instrText", "rPr", "pPr", "tblPr", "trPr", "tcPr", "sectPr", "fldData"})
_BLANK_LINES = re.compile(r"\n{3,}")


class DocxParser(Parser):
    """Extract text from a Word ``.docx`` document using only the standard library and ``lxml``.

    The body is read in document order: each paragraph on its own line, and
    each table row as its cells joined by tabs. Tabs and line breaks inside a
    paragraph are kept. Deleted revisions and field codes are left out, while
    inserted revisions and hyperlink text are kept. Headers and footers are
    not read. With ``include_notes``, footnotes and endnotes follow the body.

    The XML is parsed without resolving entities or loading DTDs, and a part
    that decompresses to more than ``max_part_bytes`` is refused, so a hostile
    file cannot exhaust memory.
    """

    def __init__(self, include_notes: bool = False, max_part_bytes: int = _DEFAULT_MAX_PART_BYTES) -> None:
        """Configure the parser.

        Raises:
            ValueError: ``max_part_bytes`` is less than 1.
        """
        if max_part_bytes < 1:
            raise ValueError("max_part_bytes must be a positive integer")
        self._include_notes = include_notes
        self._max_part_bytes = max_part_bytes

    def extract_text(self, content: bytes) -> str:
        """Return the document's text.

        Raises:
            ParsingError: The bytes are not a zip archive, the archive has no
                ``word/document.xml``, a part is not well-formed XML, or a part
                is larger than ``max_part_bytes`` once decompressed.
        """
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise ParsingError("DOCX payload is not a zip archive") from exc
        with archive:
            names = set(archive.namelist())
            if _DOCUMENT_PART not in names:
                raise ParsingError("DOCX archive has no word/document.xml")
            blocks = self._blocks(self._read_part(archive, _DOCUMENT_PART))
            if self._include_notes:
                for part in _NOTE_PARTS:
                    if part in names:
                        blocks.extend(self._note_blocks(self._read_part(archive, part)))
        text = "\n".join(blocks)
        return _BLANK_LINES.sub("\n\n", text).strip()

    def _read_part(self, archive: zipfile.ZipFile, name: str) -> etree._Element:
        with archive.open(name) as handle:
            data = handle.read(self._max_part_bytes + 1)
        if len(data) > self._max_part_bytes:
            raise ParsingError(f"DOCX part {name} is larger than {self._max_part_bytes} bytes")
        return parse_untrusted_xml(data, f"DOCX part {name}")

    def _blocks(self, root: etree._Element) -> list[str]:
        blocks: list[str] = []
        body = next((child for child in root if local_name(child) == "body"), None)
        if body is not None:
            self._collect_blocks(body, blocks)
        return blocks

    def _note_blocks(self, root: etree._Element) -> list[str]:
        blocks: list[str] = []
        for note in root:
            if local_name(note) in {"footnote", "endnote"} and note.get(_attribute(note, "type")) is None:
                self._collect_blocks(note, blocks)
        return blocks

    def _collect_blocks(self, container: etree._Element, blocks: list[str]) -> None:
        for child in container:
            name = local_name(child)
            if name == "p":
                blocks.append(self._paragraph_text(child))
            elif name == "tbl":
                blocks.extend(self._table_rows(child))
            elif name in {"sdt", "sdtContent", "customXml", "ins"}:
                self._collect_blocks(child, blocks)

    def _table_rows(self, table: etree._Element) -> list[str]:
        rows: list[str] = []
        for row in table:
            if local_name(row) != "tr":
                continue
            cells: list[str] = []
            for cell in row:
                if local_name(cell) != "tc":
                    continue
                cell_blocks: list[str] = []
                self._collect_blocks(cell, cell_blocks)
                cells.append(" ".join(block for block in cell_blocks if block))
            rows.append("\t".join(cells))
        return rows

    def _paragraph_text(self, paragraph: etree._Element) -> str:
        parts: list[str] = []
        self._collect_runs(paragraph, parts)
        return "".join(parts)

    def _collect_runs(self, element: etree._Element, parts: list[str]) -> None:
        for child in element:
            name = local_name(child)
            if name in _SKIPPED or not name:
                continue
            if name == "t":
                parts.append(child.text or "")
            elif name == "tab":
                parts.append("\t")
            elif name in {"br", "cr"}:
                parts.append("\n")
            elif name == "noBreakHyphen":
                parts.append("-")
            else:
                self._collect_runs(child, parts)


def _attribute(element: etree._Element, name: str) -> str:
    namespace = etree.QName(element).namespace
    return f"{{{namespace}}}{name}" if namespace else name
