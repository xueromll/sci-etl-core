from sci_etl_core.parsers.base import Parser, TableParser
from sci_etl_core.parsers.html import HtmlTextParser
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser
from sci_etl_core.parsers.reference_trimmer import DEFAULT_TRIM_PATTERNS, trim_after_references

__all__ = [
    "DEFAULT_TRIM_PATTERNS",
    "HtmlTextParser",
    "LatexTarballParser",
    "Parser",
    "PdfPlumberParser",
    "TableParser",
    "trim_after_references",
]
