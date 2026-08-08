from __future__ import annotations

import asyncio

from sci_etl_core.parsers.pdf import PdfPlumberParser


class AsyncPdfPlumberParser:
    def __init__(self, sync_parser: PdfPlumberParser | None = None) -> None:
        self._sync = sync_parser or PdfPlumberParser()

    async def extract_text(self, content: bytes) -> str:
        return await asyncio.to_thread(self._sync.extract_text, content)

    async def extract_tables(self, content: bytes) -> str:
        return await asyncio.to_thread(self._sync.extract_tables, content)
