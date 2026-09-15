from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from sci_etl_core.exceptions import SearchQueryError
from sci_etl_core.search.compile_fts5 import require_rankable
from sci_etl_core.search.query import FIELDS, And, Node, Not, Or, Phrase, Term, normalize, semantic_text
from sci_etl_core.search.tokenize import Token, Unicode61Tokenizer

MAX_GROUP_DEPTH = 32

_TOKENIZER = Unicode61Tokenizer()
_FIELD_SCOPE = re.compile(r"[A-Za-z]+(?:,[A-Za-z]+)*:")
_WORD_BREAKS = frozenset('()"')
_SYMBOL_OPERATORS = ("&&", "||")


class _Kind(Enum):
    OPERAND = "operand"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    OPEN = "("
    CLOSE = ")"
    END = "end"


_KEYWORDS = {"AND": _Kind.AND, "OR": _Kind.OR, "NOT": _Kind.NOT}
_SYMBOLS = {"&&": _Kind.AND, "||": _Kind.OR, "-": _Kind.NOT, "(": _Kind.OPEN, ")": _Kind.CLOSE}
_OPERAND_STARTS = frozenset({_Kind.OPERAND, _Kind.OPEN, _Kind.NOT})


@dataclass(frozen=True, slots=True)
class _Lexeme:
    kind: _Kind
    text: str
    position: int
    node: Node | None = None


def parse_query(text: str, *, default_fields: Sequence[str] = ()) -> Node:
    """Parse a Boolean query into a normalized AST.

    Syntax, with ``NOT`` binding tightest, then ``AND``, then ``OR``:

    - ``galaxy`` is a term, folded by :class:`Unicode61Tokenizer`. A word the
      tokenizer splits, such as ``H-alpha``, is a phrase of its parts.
    - ``"dwarf galaxy"`` is a phrase; a quoted single word is a term.
    - ``photometr*`` is a prefix term. The ``*`` must directly follow one word.
    - ``title:quasar`` and ``title,abstract:"dwarf galaxy"`` scope a term or a
      phrase to fields, named case-insensitively from :data:`FIELDS`.
    - ``a AND b``, ``a && b``, and ``a b`` are conjunctions; ``a OR b`` and
      ``a || b`` are disjunctions; ``NOT a`` and ``-a`` are negations.
    - Parentheses group, nesting at most :data:`MAX_GROUP_DEPTH` deep.

    Operators are upper case; ``and`` is an ordinary word. A term or phrase
    without a scope gets ``default_fields``, and empty means every field.

    Parsing is pure: it runs nothing and touches no I/O.

    Raises:
        SearchQueryError: The query is empty or malformed. ``position`` and
            ``token`` locate the first fault, with
            ``text[position:position + len(token)] == token``. A name in
            ``default_fields`` that is not in :data:`FIELDS` raises it with
            ``position=None``.
    """
    for name in default_fields:
        if name not in FIELDS:
            raise _unknown_field(name, None)
    scope = tuple(field for field in FIELDS if field in default_fields)
    return normalize(_Parser(_Scanner(text, scope)).parse())


def parse_ranked_query(text: str, *, default_fields: Sequence[str] = ()) -> Node:
    """Parse a query for a ranked search, which needs a term that is not negated.

    This is :func:`parse_query` followed by
    :func:`~sci_etl_core.search.compile_fts5.require_rankable`, with the
    rankability error located in ``text``.

    Raises:
        SearchQueryError: The query is malformed, as for :func:`parse_query`,
            or it cannot be ranked, such as ``NOT b`` or ``a OR -b``. A query
            that cannot be ranked is located at its first ``NOT`` or ``-``.
    """
    node = parse_query(text, default_fields=default_fields)
    try:
        require_rankable(node)
    except SearchQueryError as error:
        position, token = _locate(text, _is_negation)
        raise SearchQueryError(str(error), position=position, token=token) from None
    return node


def parse_semantic_query(text: str, *, default_fields: Sequence[str] = ()) -> tuple[Node, str]:
    """Parse a query for a semantic search, returning the AST and the text to embed.

    The text is :func:`~sci_etl_core.search.query.semantic_text` of the AST.

    Raises:
        SearchQueryError: The query is malformed or cannot be ranked, as for
            :func:`parse_ranked_query`, or every term that is not negated is a
            prefix term, so there is nothing to embed. That last error is
            located at the first prefix term.
    """
    node = parse_ranked_query(text, default_fields=default_fields)
    meaning = semantic_text(node)
    if not meaning:
        position, token = _locate(text, _is_prefix_term)
        raise SearchQueryError(
            "A semantic search needs at least one whole word; prefix terms match lexically only",
            position=position,
            token=token,
        )
    return node, meaning


def _locate(text: str, wanted: Callable[[_Lexeme], bool]) -> tuple[int, str]:
    scanner = _Scanner(text, ())
    lexeme = scanner.next()
    while lexeme.kind is not _Kind.END and not wanted(lexeme):
        lexeme = scanner.next()
    return lexeme.position, lexeme.text


def _is_negation(lexeme: _Lexeme) -> bool:
    return lexeme.kind is _Kind.NOT


def _is_prefix_term(lexeme: _Lexeme) -> bool:
    return isinstance(lexeme.node, Term) and lexeme.node.prefix


def _unknown_field(name: str, position: int | None) -> SearchQueryError:
    return SearchQueryError(
        f"Unknown field {name!r}; expected one of {', '.join(FIELDS)}", position=position, token=name
    )


class _Scanner:
    def __init__(self, text: str, default_fields: tuple[str, ...]) -> None:
        self._text = text
        self._default_fields = default_fields
        self._index = 0

    def next(self) -> _Lexeme:
        text = self._text
        start = self._index
        while start < len(text) and text[start].isspace():
            start += 1
        if start == len(text):
            return _Lexeme(_Kind.END, "", start)
        symbol = text[start : start + 2] if text.startswith(_SYMBOL_OPERATORS, start) else text[start]
        if symbol in _SYMBOLS:
            self._index = start + len(symbol)
            return _Lexeme(_SYMBOLS[symbol], symbol, start)
        if symbol == '"':
            return self._phrase(start, start, self._default_fields)
        return self._word(start)

    def _word(self, start: int) -> _Lexeme:
        text = self._text
        end = start
        while end < len(text) and not self._breaks_word(end):
            end += 1
        self._index = end
        raw = text[start:end]
        if raw in _KEYWORDS:
            return _Lexeme(_KEYWORDS[raw], raw, start)
        scope = _FIELD_SCOPE.match(raw)
        if scope is None:
            return _Lexeme(_Kind.OPERAND, raw, start, _word_node(raw, start, self._default_fields))
        fields = _scoped_fields(scope.group()[:-1], start)
        body_start = start + scope.end()
        if body_start < end:
            return _Lexeme(_Kind.OPERAND, raw, start, _word_node(text[body_start:end], body_start, fields))
        if text.startswith('"', end):
            return self._phrase(start, end, fields)
        raise SearchQueryError(
            f"Field scope {raw!r} must be directly followed by a word or a quoted phrase", position=start, token=raw
        )

    def _breaks_word(self, index: int) -> bool:
        text = self._text
        return text[index].isspace() or text[index] in _WORD_BREAKS or text.startswith(_SYMBOL_OPERATORS, index)

    def _phrase(self, start: int, quote: int, fields: tuple[str, ...]) -> _Lexeme:
        text = self._text
        closing = text.find('"', quote + 1)
        if closing < 0:
            raise SearchQueryError("Quoted phrase is never closed", position=quote, token='"')
        self._index = closing + 1
        quoted = text[quote : closing + 1]
        node = _leaf(_TOKENIZER.tokens(quoted[1:-1]), fields, quoted, quote)
        return _Lexeme(_Kind.OPERAND, text[start : closing + 1], start, node)


def _scoped_fields(names: str, position: int) -> tuple[str, ...]:
    requested: set[str] = set()
    for name in names.split(","):
        field = name.lower()
        if field not in FIELDS:
            raise _unknown_field(name, position)
        requested.add(field)
        position += len(name) + 1
    return tuple(field for field in FIELDS if field in requested)


def _word_node(word: str, position: int, fields: tuple[str, ...]) -> Node:
    if not word.endswith("*"):
        return _leaf(_TOKENIZER.tokens(word), fields, word, position)
    stem = word[:-1]
    tokens = _TOKENIZER.tokens(stem)
    if len(tokens) != 1 or tokens[0].end != len(stem):
        raise SearchQueryError("'*' must directly follow a single word", position=position + len(stem), token="*")
    return Term(tokens[0].text, fields, prefix=True)


def _leaf(tokens: list[Token], fields: tuple[str, ...], source: str, position: int) -> Node:
    if not tokens:
        raise SearchQueryError(f"{source!r} contains no word to search for", position=position, token=source)
    if len(tokens) == 1:
        return Term(tokens[0].text, fields)
    return Phrase(tuple(token.text for token in tokens), fields)


class _Parser:
    def __init__(self, scanner: _Scanner) -> None:
        self._scanner = scanner
        self._current = scanner.next()
        self._previous = self._current

    def parse(self) -> Node:
        if self._current.kind is _Kind.END:
            raise SearchQueryError("The query is empty", position=0)
        node = self._disjunction(0)
        if self._current.kind is _Kind.CLOSE:
            raise SearchQueryError("')' has no matching '('", position=self._current.position, token=")")
        return node

    def _advance(self) -> None:
        self._previous = self._current
        self._current = self._scanner.next()

    def _disjunction(self, depth: int) -> Node:
        operands = [self._conjunction(depth)]
        while self._current.kind is _Kind.OR:
            self._advance()
            operands.append(self._conjunction(depth))
        return Or(tuple(operands))

    def _conjunction(self, depth: int) -> Node:
        operands = [self._negation(depth)]
        while self._current.kind is _Kind.AND or self._current.kind in _OPERAND_STARTS:
            if self._current.kind is _Kind.AND:
                self._advance()
            operands.append(self._negation(depth))
        return And(tuple(operands))

    def _negation(self, depth: int) -> Node:
        negations = 0
        while self._current.kind is _Kind.NOT:
            negations += 1
            self._advance()
        operand = self._primary(depth)
        return Not(operand) if negations % 2 else operand

    def _primary(self, depth: int) -> Node:
        lexeme = self._current
        if lexeme.node is not None:
            self._advance()
            return lexeme.node
        if lexeme.kind is _Kind.OPEN:
            return self._group(lexeme, depth + 1)
        if lexeme.kind is _Kind.END:
            operator = self._previous
            raise SearchQueryError(
                f"Expected a search term after {operator.text!r}", position=operator.position, token=operator.text
            )
        raise SearchQueryError(
            f"Expected a search term before {lexeme.text!r}", position=lexeme.position, token=lexeme.text
        )

    def _group(self, opening: _Lexeme, depth: int) -> Node:
        if depth > MAX_GROUP_DEPTH:
            raise SearchQueryError(
                f"Parentheses nest more than {MAX_GROUP_DEPTH} deep", position=opening.position, token="("
            )
        self._advance()
        node = self._disjunction(depth)
        if self._current.kind is not _Kind.CLOSE:
            raise SearchQueryError("'(' is never closed", position=opening.position, token="(")
        self._advance()
        return node
