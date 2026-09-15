from __future__ import annotations

import re
from collections.abc import Iterable

from sci_etl_core.exceptions import SearchQueryError
from sci_etl_core.search.query import And, Node, Not, Or, Phrase, Term, normalize

_UNSENDABLE = re.compile(r"[\x00\ud800-\udfff]")


def is_rankable(node: Node) -> bool:
    """Report whether ``node`` compiles to a single FTS5 MATCH expression, and so can be ranked.

    FTS5 has no unary ``NOT``; its ``NOT`` subtracts one match set from another.
    After :func:`~sci_etl_core.search.query.normalize`:

    - a :class:`Term` or :class:`Phrase` is rankable;
    - an :class:`Or` is rankable when every operand is;
    - an :class:`And` is rankable when every operand that is not a :class:`Not`
      is rankable, and so is the operand of its :class:`Not`, if it has one;
    - a :class:`Not` on its own is not rankable.

    Normalization leaves every ``And`` with at least one operand that is not a
    ``Not``, and at most one that is.
    """
    return _compile(normalize(node)) is not None


def require_rankable(node: Node) -> None:
    """Raise unless ``node`` can be ranked, as :func:`is_rankable` defines it.

    Raises:
        SearchQueryError: ``node`` is not rankable, such as ``NOT b`` or
            ``NOT b OR c``. ``position`` is ``None``, because an AST carries no
            offsets into the text it was parsed from.
    """
    if not is_rankable(node):
        raise _not_rankable()


def to_match_expression(node: Node) -> str:
    """Compile the normalized ``node`` into one FTS5 MATCH expression.

    Every word reaches FTS5 inside a double-quoted string literal with each
    ``"`` doubled, so no query text can act as an FTS5 operator. Bind the result
    as a ``?`` parameter; never format it into SQL. SQLite cannot take a NUL or
    a surrogate inside a literal, so each becomes a space; the tokenizer treats
    both as separators, so what matches is unchanged.

    Every ``AND``, ``OR``, and nested ``NOT`` is parenthesized, so FTS5 operator
    precedence never decides the meaning.

    Raises:
        SearchQueryError: ``node`` is not rankable (:func:`require_rankable`).
    """
    expression = _compile(normalize(node))
    if expression is None:
        raise _not_rankable()
    return expression


def _not_rankable() -> SearchQueryError:
    return SearchQueryError(
        "A ranked search needs at least one term that is not negated, and so does each OR alternative"
    )


def _compile(node: Node) -> str | None:
    if isinstance(node, Term):
        return _scoped(node.fields, _quote(node.text) + ("*" if node.prefix else ""))
    if isinstance(node, Phrase):
        return _scoped(node.fields, _quote(" ".join(node.words)))
    if isinstance(node, Or):
        alternatives = _compile_each(node.operands)
        return None if alternatives is None else "(" + " OR ".join(alternatives) + ")"
    if isinstance(node, And):
        kept = _compile_each(operand for operand in node.operands if not isinstance(operand, Not))
        removed = _compile_each(operand.operand for operand in node.operands if isinstance(operand, Not))
        if kept is None or removed is None:
            return None
        included = kept[0] if len(kept) == 1 else "(" + " AND ".join(kept) + ")"
        return f"{included} NOT {removed[0]}" if removed else included
    return None


def _compile_each(operands: Iterable[Node]) -> list[str] | None:
    compiled: list[str] = []
    for operand in operands:
        expression = _compile(operand)
        if expression is None:
            return None
        compiled.append(f"({expression})" if _subtracts(operand) else expression)
    return compiled


def _subtracts(node: Node) -> bool:
    return isinstance(node, And) and any(isinstance(operand, Not) for operand in node.operands)


def _scoped(fields: tuple[str, ...], literal: str) -> str:
    return ("{" + " ".join(fields) + "} : " + literal) if fields else literal


def _quote(text: str) -> str:
    return '"' + _UNSENDABLE.sub(" ", text).replace('"', '""') + '"'
