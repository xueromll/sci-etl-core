from __future__ import annotations

import io

import pdfplumber

from sci_etl_core.exceptions import ParsingError
from sci_etl_core.parsers.base import Parser, TableParser


class PdfPlumberParser(Parser, TableParser):
    def extract_text(self, content: bytes) -> str:
        """Return the text of every page, followed by any tables found.

        Raises:
            ParsingError: The payload is not a readable PDF.
        """
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() for page in pdf.pages if page]
        except Exception as exc:
            raise ParsingError(f"PDF could not be parsed: {exc!r}") from exc
        body = "\n".join(page for page in pages if page)
        tables = self.extract_tables(content)
        return f"{body}\n\n--- EXTRACTED TABLES ---\n{tables}" if tables else body

    def extract_tables(self, content: bytes) -> str:
        """Return tables as pipe-separated rows, or ``""`` if none can be read.

        Tables supplement the page text, so a table-extraction failure yields
        an empty result rather than discarding text that was already read.
        """
        rows: list[str] = []
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    for table in page.extract_tables():
                        if table:
                            rows.append(
                                "\n".join(" | ".join(str(cell) if cell else "" for cell in row) for row in table)
                            )
        except Exception:
            return ""
        return "\n".join(rows)
