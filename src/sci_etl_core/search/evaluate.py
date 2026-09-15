from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sci_etl_core.search.query import FIELDS, And, Node, Not, Or, Phrase, Term
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.tokenize import Tokenizer, Unicode61Tokenizer

_UNICODE61 = Unicode61Tokenizer()


@dataclass(frozen=True, slots=True)
class TokenizedDocument:
    """A document's fields as token texts, tokenized once to be matched many times."""

    title: tuple[str, ...] = ()
    abstract: tuple[str, ...] = ()
    body: tuple[str, ...] = ()

    @classmethod
    def from_document(cls, document: SearchDocument, tokenizer: Tokenizer | None = None) -> TokenizedDocument:
        """Tokenize every field of ``document``, by default with :class:`Unicode61Tokenizer`."""
        active = _UNICODE61 if tokenizer is None else tokenizer
        return cls(_words(active, document.title), _words(active, document.abstract), _words(active, document.body))


def matches(node: Node, document: SearchDocument | TokenizedDocument, *, tokenizer: Tokenizer | None = None) -> bool:
    """Report whether ``document`` satisfies the Boolean query ``node``.

    The semantics are those FTS5 gives the expression that
    :func:`~sci_etl_core.search.compile_fts5.to_match_expression` builds:

    - The text of a :class:`Term` and the words of a
      :class:`~sci_etl_core.search.query.Phrase` are tokenized again, as FTS5
      tokenizes a quoted string. Text that splits into several tokens matches
      as a phrase, and text with no token matches nothing.
    - A phrase matches consecutive tokens within one field. With ``prefix``, a
      term's last token matches every token that starts with it.
    - A leaf without ``fields`` searches every field.

    Any query can be evaluated, including a pure negation such as ``NOT b``.
    ``node`` is interpreted exactly as given, without
    :func:`~sci_etl_core.search.query.normalize`, so evaluation stays an
    independent check on normalization.

    ``tokenizer`` defaults to :class:`Unicode61Tokenizer`. It splits the query's
    words, and ``document`` unless it is already a :class:`TokenizedDocument`,
    which must then come from the same tokenizer.
    """
    active = _UNICODE61 if tokenizer is None else tokenizer
    if isinstance(document, SearchDocument):
        document = TokenizedDocument.from_document(document, active)
    return _satisfies(node, document, active)


def occurrences(
    leaf: Term | Phrase, document: TokenizedDocument, *, tokenizer: Tokenizer | None = None
) -> dict[str, list[tuple[int, int]]]:
    """Return where ``leaf`` occurs in ``document``, as ``[start, stop)`` token ranges per field.

    Only the fields ``leaf`` searches are considered, with the same semantics as
    :func:`matches`, and a field without an occurrence is omitted. Overlapping
    occurrences are all reported: the phrase ``a a`` occurs twice in ``a a a``.
    """
    active = _UNICODE61 if tokenizer is None else tokenizer
    query = _leaf_words(active, leaf)
    found: dict[str, list[tuple[int, int]]] = {}
    for name in leaf.fields or FIELDS:
        ranges = [(start, start + len(query)) for start in _starts(getattr(document, name), query, _is_prefix(leaf))]
        if ranges:
            found[name] = ranges
    return found


def _satisfies(node: Node, document: TokenizedDocument, tokenizer: Tokenizer) -> bool:
    if isinstance(node, Not):
        return not _satisfies(node.operand, document, tokenizer)
    if isinstance(node, And):
        return all(_satisfies(operand, document, tokenizer) for operand in node.operands)
    if isinstance(node, Or):
        return any(_satisfies(operand, document, tokenizer) for operand in node.operands)
    query = _leaf_words(tokenizer, node)
    prefix = _is_prefix(node)
    return any(
        next(_starts(getattr(document, name), query, prefix), None) is not None for name in node.fields or FIELDS
    )


def _starts(tokens: tuple[str, ...], query: tuple[str, ...], prefix: bool) -> Iterator[int]:
    if not query:
        return
    leading, last = query[:-1], query[-1]
    for start in range(len(tokens) - len(leading)):
        candidate = tokens[start + len(leading)]
        last_matches = candidate.startswith(last) if prefix else candidate == last
        if last_matches and tokens[start : start + len(leading)] == leading:
            yield start


def _leaf_words(tokenizer: Tokenizer, leaf: Term | Phrase) -> tuple[str, ...]:
    return _words(tokenizer, leaf.text if isinstance(leaf, Term) else " ".join(leaf.words))


def _is_prefix(leaf: Term | Phrase) -> bool:
    return isinstance(leaf, Term) and leaf.prefix


def _words(tokenizer: Tokenizer, text: str) -> tuple[str, ...]:
    return tuple(token.text for token in tokenizer.tokens(text))
