from __future__ import annotations

import pytest

from sci_etl_core.parsers.pdf_async import AsyncPdfPlumberParser


def _cm(mocker, pages):
    pdf = mocker.MagicMock()
    pdf.pages = pages
    pdf.__enter__.return_value = pdf
    pdf.__exit__.return_value = False
    return pdf


def _page(mocker, text=None, tables=None):
    page = mocker.MagicMock()
    page.extract_text.return_value = text
    page.extract_tables.return_value = tables if tables is not None else []
    return page


class TestAsyncPdfPlumberParser:
    @pytest.mark.asyncio
    async def test_returns_body_without_tables(self, mocker):
        pdf = _cm(mocker, [_page(mocker, text="Body")])
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", return_value=pdf)
        assert await AsyncPdfPlumberParser().extract_text(b"x") == "Body"

    @pytest.mark.asyncio
    async def test_appends_tables_section(self, mocker):
        pdf = _cm(mocker, [_page(mocker, text="Body", tables=[[["a", "b"], ["c", "d"]]])])
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", return_value=pdf)
        result = await AsyncPdfPlumberParser().extract_text(b"x")
        assert "Body" in result
        assert "--- EXTRACTED TABLES ---" in result
        assert "a | b" in result

    @pytest.mark.asyncio
    async def test_returns_empty_on_corrupted_pdf(self, mocker):
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", side_effect=Exception("corrupt"))
        assert await AsyncPdfPlumberParser().extract_tables(b"garbage") == ""
