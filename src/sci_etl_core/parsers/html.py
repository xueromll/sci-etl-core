from __future__ import annotations

import re

from bs4 import BeautifulSoup

from sci_etl_core.parsers.base import Parser

_WHITESPACE = re.compile(r"\s+")


class HtmlTextParser(Parser):
    def extract_text(self, content: bytes) -> str:
        text = BeautifulSoup(content, "html.parser").get_text(separator=" ", strip=True)
        return _WHITESPACE.sub(" ", text).strip()
