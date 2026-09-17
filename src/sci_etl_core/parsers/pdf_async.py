from __future__ import annotations

import asyncio

from sci_etl_core.parsers.pdf import PdfPlumberParser


class AsyncPdfPlumberParser:
    """Run a :class:`~sci_etl_core.parsers.pdf.PdfPlumberParser` in a worker thread, off the event loop."""

    def __init__(self, sync_parser: PdfPlumberParser | None = None) -> None:
        """Wrap ``sync_parser``, or a new ``PdfPlumberParser`` when it is ``None``."""
        self._sync = sync_parser or PdfPlumberParser()

    async def extract_text(self, content: bytes) -> str:
        """Return the PDF's text, as :meth:`PdfPlumberParser.extract_text` does.

        Raises:
            ParsingError: The payload is not a readable PDF.
        """
        return await asyncio.to_thread(self._sync.extract_text, content)

    async def extract_tables(self, content: bytes) -> str:
        """Return the PDF's tables, as :meth:`PdfPlumberParser.extract_tables` does."""
        return await asyncio.to_thread(self._sync.extract_tables, content)
