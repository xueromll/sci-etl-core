from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "DEFAULT_TRIM_PATTERNS": "sci_etl_core.parsers.reference_trimmer",
    "HtmlTextParser": "sci_etl_core.parsers.html",
    "LatexTarballParser": "sci_etl_core.parsers.latex",
    "Parser": "sci_etl_core.parsers.base",
    "PdfPlumberParser": "sci_etl_core.parsers.pdf",
    "TableParser": "sci_etl_core.parsers.base",
    "trim_after_references": "sci_etl_core.parsers.reference_trimmer",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.parsers.base import Parser, TableParser
    from sci_etl_core.parsers.html import HtmlTextParser
    from sci_etl_core.parsers.latex import LatexTarballParser
    from sci_etl_core.parsers.pdf import PdfPlumberParser
    from sci_etl_core.parsers.reference_trimmer import DEFAULT_TRIM_PATTERNS, trim_after_references
