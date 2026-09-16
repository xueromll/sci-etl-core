from __future__ import annotations

from dataclasses import dataclass

FIELDS: tuple[str, ...] = ("title", "abstract", "body")
"""The text fields of a document, in index column order; a term or phrase can be scoped to any of them."""


def _require_known_fields(fields: tuple[str, ...]) -> None:
    for name in fields:
        if name not in FIELDS:
            raise ValueError(f"Unknown field {name!r}; expected one of {', '.join(FIELDS)}")
    if len(set(fields)) != len(fields):
        raise ValueError(f"fields must not repeat a field: {fields!r}")


@dataclass(frozen=True, slots=True)
class Term:
    """One tokenizer-normalized word, matched exactly or, with ``prefix``, as a prefix.

    ``fields`` limits the match to those fields; empty means every field.

    Raises:
        ValueError: ``text`` is empty, or ``fields`` names an unknown field or
            repeats one.
    """

    text: str
    fields: tuple[str, ...] = ()
    prefix: bool = False

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("A term needs non-empty text")
        _require_known_fields(self.fields)


@dataclass(frozen=True, slots=True)
class Phrase:
    """Tokenizer-normalized words that must appear adjacent and in this order.

    ``fields`` limits the match to those fields; empty means every field.

    Raises:
        ValueError: ``words`` is empty or holds an empty word, or ``fields``
            names an unknown field or repeats one.
    """

    words: tuple[str, ...]
    fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.words or not all(self.words):
            raise ValueError("A phrase needs at least one word, and no word may be empty")
        _require_known_fields(self.fields)


NEAR_DISTANCE = 10
"""The default :attr:`Near.distance`, as in FTS5."""


@dataclass(frozen=True, slots=True)
class Near:
    """Terms and phrases that must all occur in one field, close to each other, in any order.

    With the occurrences chosen so that the one starting last starts at token
    ``p``, every other operand must end at most ``distance`` tokens before
    ``p``: ``NEAR(a b, 2)`` matches ``a x x b`` and ``b x a`` but not
    ``a x x x b``. The operands carry no field scope of their own; ``fields``
    limits the whole group, and empty means any one field.

    Raises:
        ValueError: There are fewer than two operands, an operand has fields
            of its own, ``distance`` is negative, or ``fields`` names an unknown
            field or repeats one.
    """

    operands: tuple[Term | Phrase, ...]
    distance: int = NEAR_DISTANCE
    fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.operands) < 2:
            raise ValueError("NEAR needs at least two terms or phrases")
        if any(operand.fields for operand in self.operands):
            raise ValueError("The terms and phrases inside NEAR cannot have fields of their own; scope the group")
        if self.distance < 0:
            raise ValueError(f"NEAR distance must not be negative, not {self.distance!r}")
        _require_known_fields(self.fields)

    def scoped_operands(self) -> tuple[Term | Phrase, ...]:
        """Return the operands with the group's fields applied to each."""
        if not self.fields:
            return self.operands
        return tuple(
            Term(operand.text, self.fields, operand.prefix)
            if isinstance(operand, Term)
            else Phrase(operand.words, self.fields)
            for operand in self.operands
        )


@dataclass(frozen=True, slots=True)
class And:
    """Matches when every operand matches.

    Raises:
        ValueError: ``operands`` is empty.
    """

    operands: tuple[Node, ...]

    def __post_init__(self) -> None:
        if not self.operands:
            raise ValueError("And needs at least one operand")


@dataclass(frozen=True, slots=True)
class Or:
    """Matches when any operand matches.

    Raises:
        ValueError: ``operands`` is empty.
    """

    operands: tuple[Node, ...]

    def __post_init__(self) -> None:
        if not self.operands:
            raise ValueError("Or needs at least one operand")


@dataclass(frozen=True, slots=True)
class Not:
    """Matches when its operand does not."""

    operand: Node


Node = Term | Phrase | Near | And | Or | Not


def normalize(node: Node) -> Node:
    """Return the canonical form of ``node``, which ``normalize`` leaves unchanged.

    The rules apply bottom-up until nothing changes:

    1. ``Not(Not(x))`` becomes ``x``.
    2. Nested ``And`` and ``Or`` flatten, and a single-operand ``And`` or ``Or``
       becomes its operand.
    3. Inside an ``And``, two or more ``Not`` operands merge by De Morgan's law
       into one, placed where the first stood:
       ``And((a, Not(b), Not(c)))`` becomes ``And((a, Not(Or((b, c)))))``.
    4. Operand order is preserved, never sorted.

    The result matches exactly the documents ``node`` matches.
    """
    if isinstance(node, Not):
        operand = normalize(node.operand)
        return operand.operand if isinstance(operand, Not) else Not(operand)
    if isinstance(node, Or):
        return _collapse(Or, _flatten(Or, node.operands))
    if isinstance(node, And):
        return _collapse(And, _merge_negations(_flatten(And, node.operands)))
    return node


def _flatten(kind: type[And] | type[Or], operands: tuple[Node, ...]) -> list[Node]:
    flat: list[Node] = []
    for operand in operands:
        normalized = normalize(operand)
        if isinstance(normalized, kind):
            flat.extend(normalized.operands)
        else:
            flat.append(normalized)
    return flat


def _merge_negations(operands: list[Node]) -> list[Node]:
    negated = [operand.operand for operand in operands if isinstance(operand, Not)]
    if len(negated) < 2:
        return operands
    first_negation = next(index for index, operand in enumerate(operands) if isinstance(operand, Not))
    merged: list[Node] = [operand for operand in operands if not isinstance(operand, Not)]
    merged.insert(first_negation, Not(_collapse(Or, _flatten(Or, tuple(negated)))))
    return merged


def _collapse(kind: type[And] | type[Or], operands: list[Node]) -> Node:
    return operands[0] if len(operands) == 1 else kind(tuple(operands))


@dataclass(frozen=True, slots=True)
class QueryChip:
    """One word or phrase of a query, labelled for display.

    ``text`` is the term, or the phrase's words joined by single spaces.
    ``fields`` is empty when every field is searched. ``operator`` is ``"AND"``
    or ``"OR"``, the operator of the innermost group holding the chip, and is
    empty when the whole query is this one word or phrase. ``negated`` is true
    when the chip must not match, and ``depth`` counts the groups around it, so
    a UI can bracket ``a (b OR c)`` without re-implementing the grammar.
    ``near`` is the distance of the ``NEAR`` group the chip stands for, whose
    ``text`` is then its terms and phrases, phrases in double quotes, joined by
    single spaces; it is ``None`` for any other chip.
    """

    text: str
    fields: tuple[str, ...] = ()
    operator: str = ""
    negated: bool = False
    prefix: bool = False
    phrase: bool = False
    depth: int = 0
    near: int | None = None


def describe(node: Node) -> list[QueryChip]:
    """Return the words and phrases of ``node`` as chips, in the order they were written.

    ``node`` is normalized first, so ``NOT NOT a`` is described as ``a``.
    """
    chips: list[QueryChip] = []
    _describe(normalize(node), "", False, 0, chips)
    return chips


def _describe(node: Node, operator: str, negated: bool, depth: int, chips: list[QueryChip]) -> None:
    if isinstance(node, Not):
        _describe(node.operand, operator, not negated, depth, chips)
    elif isinstance(node, (And, Or)):
        group = "AND" if isinstance(node, And) else "OR"
        for operand in node.operands:
            _describe(operand, group, negated, depth + 1, chips)
    elif isinstance(node, Term):
        chips.append(QueryChip(node.text, node.fields, operator, negated, node.prefix, False, max(depth - 1, 0)))
    elif isinstance(node, Near):
        text = " ".join(_near_operand_text(operand) for operand in node.operands)
        chips.append(QueryChip(text, node.fields, operator, negated, False, False, max(depth - 1, 0), node.distance))
    else:
        chips.append(QueryChip(" ".join(node.words), node.fields, operator, negated, False, True, max(depth - 1, 0)))


def _near_operand_text(operand: Term | Phrase) -> str:
    if isinstance(operand, Term):
        return operand.text + ("*" if operand.prefix else "")
    return '"' + " ".join(operand.words) + '"'


def semantic_text(node: Node) -> str:
    """Return the words an embedder should see for ``node``: its meaning, not its syntax.

    ``node`` is normalized first. The text of every term and phrase that is not
    negated is joined with single spaces, in the order written. Operators,
    field scopes, and every negated subtree are dropped, so ``quasar -dwarf``
    becomes ``quasar`` rather than pulling results towards dwarfs.

    Prefix terms are left out entirely: ``photometr`` is a matching feature, not
    a word an embedder understands, so ``photometr* dwarf`` gives ``dwarf`` and
    ``photometr*`` gives the empty string.

    ``OR`` loses its meaning here. A single vector cannot represent a
    disjunction, so ``quasar OR blazar`` gives ``quasar blazar``, the same text
    as ``quasar AND blazar``.
    """
    words: list[str] = []
    _collect_meaning(normalize(node), words)
    return " ".join(words)


def _collect_meaning(node: Node, words: list[str]) -> None:
    if isinstance(node, (And, Or)):
        for operand in node.operands:
            _collect_meaning(operand, words)
    elif isinstance(node, Term):
        if not node.prefix:
            words.append(node.text)
    elif isinstance(node, Phrase):
        words.extend(node.words)
    elif isinstance(node, Near):
        for operand in node.operands:
            _collect_meaning(operand, words)
