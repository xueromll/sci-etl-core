from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "is_rankable": "sci_etl_core.search.compile_fts5",
    "require_rankable": "sci_etl_core.search.compile_fts5",
    "to_match_expression": "sci_etl_core.search.compile_fts5",
    "TokenizedDocument": "sci_etl_core.search.evaluate",
    "matches": "sci_etl_core.search.evaluate",
    "parse_query": "sci_etl_core.search.parser",
    "FIELDS": "sci_etl_core.search.query",
    "And": "sci_etl_core.search.query",
    "Node": "sci_etl_core.search.query",
    "Not": "sci_etl_core.search.query",
    "Or": "sci_etl_core.search.query",
    "Phrase": "sci_etl_core.search.query",
    "Term": "sci_etl_core.search.query",
    "normalize": "sci_etl_core.search.query",
    "SearchDocument": "sci_etl_core.search.store_base",
    "Token": "sci_etl_core.search.tokenize",
    "Tokenizer": "sci_etl_core.search.tokenize",
    "Unicode61Tokenizer": "sci_etl_core.search.tokenize",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.search.compile_fts5 import is_rankable, require_rankable, to_match_expression
    from sci_etl_core.search.evaluate import TokenizedDocument, matches
    from sci_etl_core.search.parser import parse_query
    from sci_etl_core.search.query import FIELDS, And, Node, Not, Or, Phrase, Term, normalize
    from sci_etl_core.search.store_base import SearchDocument
    from sci_etl_core.search.tokenize import Token, Tokenizer, Unicode61Tokenizer
