from __future__ import annotations

import io

import pdfplumber

from sci_etl_core.parsers.base import Parser, TableParser


class PdfPlumberParser(Parser, TableParser):
    def extract_text(self, content: bytes) -> str:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [page.extract_text() for page in pdf.pages if page]
        body = "\n".join(page for page in pages if page)
        tables = self.extract_tables(content)
        return f"{body}\n\n--- EXTRACTED TABLES ---\n{tables}" if tables else body

    def extract_tables(self, content: bytes) -> str:
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
