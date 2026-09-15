from __future__ import annotations

from dataclasses import dataclass

FIELDS: tuple[str, ...] = ("title", "abstract", "body")


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


Node = Term | Phrase | And | Or | Not


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
