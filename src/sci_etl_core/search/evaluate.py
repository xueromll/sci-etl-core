from __future__ import annotations

from dataclasses import dataclass

from sci_etl_core.search.query import FIELDS, And, Node, Not, Or, Term
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


def _satisfies(node: Node, document: TokenizedDocument, tokenizer: Tokenizer) -> bool:
    if isinstance(node, Not):
        return not _satisfies(node.operand, document, tokenizer)
    if isinstance(node, And):
        return all(_satisfies(operand, document, tokenizer) for operand in node.operands)
    if isinstance(node, Or):
        return any(_satisfies(operand, document, tokenizer) for operand in node.operands)
    if isinstance(node, Term):
        return _occurs(_words(tokenizer, node.text), node.prefix, node.fields, document)
    return _occurs(_words(tokenizer, " ".join(node.words)), False, node.fields, document)


def _occurs(query: tuple[str, ...], prefix: bool, fields: tuple[str, ...], document: TokenizedDocument) -> bool:
    if not query:
        return False
    return any(_in_sequence(getattr(document, field), query, prefix) for field in fields or FIELDS)


def _in_sequence(tokens: tuple[str, ...], query: tuple[str, ...], prefix: bool) -> bool:
    leading, last = query[:-1], query[-1]
    for start in range(len(tokens) - len(leading)):
        candidate = tokens[start + len(leading)]
        last_matches = candidate.startswith(last) if prefix else candidate == last
        if last_matches and tokens[start : start + len(leading)] == leading:
            return True
    return False


def _words(tokenizer: Tokenizer, text: str) -> tuple[str, ...]:
    return tuple(token.text for token in tokenizer.tokens(text))
