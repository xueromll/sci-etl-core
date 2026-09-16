from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sci_etl_core.search.query import FIELDS, And, Near, Node, Not, Or, Phrase, Term
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.tokenize import Tokenizer, Unicode61Tokenizer

_UNICODE61 = Unicode61Tokenizer()
_COLUMN_SHIFT = 32
_EXHAUSTED = 1 << 62

Hits = dict[str, list[tuple[int, int]]]


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
    - A :class:`~sci_etl_core.search.query.Near` group matches as
      :func:`trim_near` describes. An operand whose text has no token is
      dropped from the group, and a group left with one operand matches as
      that operand.

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


def near_occurrences(
    near: Near, document: TokenizedDocument, *, tokenizer: Tokenizer | None = None
) -> list[Hits]:
    """Return where each operand of ``near`` occurs as part of a match, one mapping per operand.

    The mappings are those of :func:`occurrences`, trimmed by :func:`trim_near`
    to the occurrences FTS5 counts, and are all empty when the group does not
    match. An operand dropped for having no token gets an empty mapping.
    """
    active = _UNICODE61 if tokenizer is None else tokenizer
    operands = near.scoped_operands()
    found = [occurrences(operand, document, tokenizer=active) for operand in operands]
    lengths = [len(_leaf_words(active, operand)) for operand in operands]
    return near_hits(found, lengths, near.distance)


def near_hits(found: list[Hits], lengths: list[int], distance: int) -> list[Hits]:
    """Apply ``NEAR`` to each operand's occurrences, given how many tokens each operand spans.

    Operands spanning no token are dropped, as FTS5 drops them, and one left
    alone keeps all its occurrences. Otherwise the result is :func:`trim_near`.
    """
    kept = [index for index, length in enumerate(lengths) if length > 0]
    result: list[Hits] = [{} for _ in found]
    if len(kept) == 1:
        result[kept[0]] = found[kept[0]]
    elif kept:
        trimmed = trim_near([found[index] for index in kept], [lengths[index] for index in kept], distance)
        for index, hits in zip(kept, trimmed, strict=True):
            result[index] = hits
    return result


def trim_near(found: list[Hits], lengths: list[int], distance: int) -> list[Hits]:
    """Keep the occurrences that FTS5 counts as part of a ``NEAR`` match, following its algorithm step for step.

    Occurrences in different fields are never near each other. A set of
    occurrences, one per operand, matches when every operand ends at most
    ``distance`` tokens before the start of the occurrence that starts last.
    FTS5 walks every operand's start positions together, and each time the
    current positions match it keeps them and advances the operand whose next
    position is smallest. The occurrences kept are exactly those it walks past
    in a match, which is what it scores and highlights, and every mapping is
    empty when no set matches.
    """
    positions = [sorted(_packed(hits)) for hits in found]
    kept: list[list[int]] = [[] for _ in found]
    if all(positions):
        _walk_near(positions, lengths, distance, kept)
    if not kept[0]:
        return [{} for _ in found]
    return [_unpacked(starts, length) for starts, length in zip(kept, lengths, strict=True)]


def _walk_near(positions: list[list[int]], lengths: list[int], distance: int, kept: list[list[int]]) -> None:
    cursor = [0] * len(positions)

    def current(index: int) -> int:
        return positions[index][cursor[index]]

    def lookahead(index: int) -> int:
        following = cursor[index] + 1
        return positions[index][following] if following < len(positions[index]) else _EXHAUSTED

    def advance(index: int) -> bool:
        cursor[index] += 1
        return cursor[index] >= len(positions[index])

    while True:
        latest = current(0)
        matched = False
        while not matched:
            matched = True
            for index in range(len(positions)):
                earliest = latest - lengths[index] - distance
                if current(index) < earliest or current(index) > latest:
                    matched = False
                    while current(index) < earliest:
                        if advance(index):
                            return
                    latest = max(latest, current(index))
        for index, starts in enumerate(kept):
            if not starts or starts[-1] != current(index):
                starts.append(current(index))
        advancing = min(range(len(positions)), key=lookahead)
        if advance(advancing):
            return


def _packed(hits: Hits) -> list[int]:
    return [(FIELDS.index(name) << _COLUMN_SHIFT) | start for name, ranges in hits.items() for start, _ in ranges]


def _unpacked(starts: list[int], length: int) -> Hits:
    hits: Hits = {}
    for packed in starts:
        start = packed & ((1 << _COLUMN_SHIFT) - 1)
        hits.setdefault(FIELDS[packed >> _COLUMN_SHIFT], []).append((start, start + length))
    return hits


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
    if isinstance(node, Near):
        return any(near_occurrences(node, document, tokenizer=tokenizer))
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
