from __future__ import annotations

from sci_etl_core.parsers.pdf import PdfPlumberParser


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


class TestExtractText:
    def test_returns_body_without_tables(self, mocker):
        pdf = _cm(mocker, [_page(mocker, text="Body")])
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", return_value=pdf)
        assert PdfPlumberParser().extract_text(b"x") == "Body"

    def test_appends_tables_section(self, mocker):
        pdf = _cm(mocker, [_page(mocker, text="Body", tables=[[["a", "b"], ["c", "d"]]])])
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", return_value=pdf)
        result = PdfPlumberParser().extract_text(b"x")
        assert "Body" in result
        assert "--- EXTRACTED TABLES ---" in result
        assert "a | b" in result
        assert "c | d" in result

    def test_handles_pages_without_text(self, mocker):
        pdf = _cm(mocker, [_page(mocker, text=None)])
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", return_value=pdf)
        assert PdfPlumberParser().extract_text(b"x") == ""


class TestExtractTables:
    def test_returns_empty_on_corrupted_pdf(self, mocker):
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", side_effect=Exception("corrupt"))
        assert PdfPlumberParser().extract_tables(b"garbage") == ""

    def test_renders_none_cells_as_empty(self, mocker):
        pdf = _cm(mocker, [_page(mocker, tables=[[["x", None], [None, "y"]]])])
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", return_value=pdf)
        assert PdfPlumberParser().extract_tables(b"x") == "x | \n | y"

    def test_skips_empty_tables(self, mocker):
        pdf = _cm(mocker, [_page(mocker, tables=[[], [["a"]]])])
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", return_value=pdf)
        assert PdfPlumberParser().extract_tables(b"x") == "a"
