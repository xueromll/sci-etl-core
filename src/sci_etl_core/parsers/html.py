from __future__ import annotations

import re

from bs4 import BeautifulSoup

from sci_etl_core.parsers.base import Parser

_WHITESPACE = re.compile(r"\s+")


class HtmlTextParser(Parser):
    """Read the visible text of an HTML document with the standard ``html.parser`` backend."""

    def extract_text(self, content: bytes) -> str:
        """Return the document's text with every run of whitespace collapsed to one space.

        Malformed markup is read leniently.
        """
        text = BeautifulSoup(content, "html.parser").get_text(separator=" ", strip=True)
        return _WHITESPACE.sub(" ", text).strip()
