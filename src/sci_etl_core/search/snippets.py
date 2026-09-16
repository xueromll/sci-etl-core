from __future__ import annotations

from collections.abc import Iterator, Sequence

from sci_etl_core.search.evaluate import TokenizedDocument, occurrences
from sci_etl_core.search.filters import SNIPPET_ELLIPSIS, SNIPPET_TOKENS, sanitize_text
from sci_etl_core.search.query import FIELDS, And, Near, Node, Not, Or, Phrase, Term, normalize
from sci_etl_core.search.store_base import Snippet
from sci_etl_core.search.tokenize import Token, Tokenizer, Unicode61Tokenizer

_UNICODE61 = Unicode61Tokenizer()


def snippet_window(
    text: str, tokens: Sequence[Token], ranges: Sequence[tuple[int, int]]
) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Cut ``text`` to a window of at most :data:`SNIPPET_TOKENS` tokens around its first highlighted range.

    ``tokens`` are the tokens of ``text``, and ``ranges`` are ``[start, stop)``
    token ranges to highlight, in any order and possibly overlapping. The window
    starts at the first range, or earlier when that range is near the end, and
    :data:`SNIPPET_ELLIPSIS` marks text left out before or after it. Returns the
    window's text and its highlights as ``[start, end)`` character offsets into
    that text, with overlapping ranges merged into one span.
    """
    spans = _merge_overlapping(sorted(ranges))
    first = spans[0][0] if spans else 0
    start = max(0, min(first, len(tokens) - SNIPPET_TOKENS))
    stop = min(len(tokens), start + SNIPPET_TOKENS)
    prefix = SNIPPET_ELLIPSIS if start > 0 else ""
    suffix = SNIPPET_ELLIPSIS if stop < len(tokens) else ""
    begin = tokens[start].start if prefix else 0
    end = tokens[stop - 1].end if suffix else len(text)
    shift = len(prefix) - begin
    highlights = tuple(
        (tokens[max(span_start, start)].start + shift, tokens[min(span_stop, stop) - 1].end + shift)
        for span_start, span_stop in spans
        if max(span_start, start) < min(span_stop, stop)
    )
    return prefix + text[begin:end] + suffix, highlights


def passage_snippet(query: Node, text: str, field: str = "body", *, tokenizer: Tokenizer | None = None) -> Snippet:
    """Return a snippet of ``text``, read as ``field``, highlighting every word of ``query`` it contains.

    Unlike a store's snippet, which highlights only the parts of the query a
    document satisfies, every term and phrase that is not negated is
    highlighted wherever it occurs, whether or not ``text`` matches the whole
    query. That suits text found another way, such as the passage a semantic
    search ranked best. A term or phrase scoped to other fields is not
    highlighted, and the terms of a ``NEAR`` group are highlighted wherever they
    occur. Without a highlight, the snippet is the start of ``text``.

    Raises:
        ValueError: ``field`` is not one of :data:`~sci_etl_core.search.query.FIELDS`.
    """
    if field not in FIELDS:
        raise ValueError(f"Unknown field {field!r}; expected one of {', '.join(FIELDS)}")
    active = _UNICODE61 if tokenizer is None else tokenizer
    clean = sanitize_text(text)
    tokens = active.tokens(clean)
    document = TokenizedDocument(**{field: tuple(token.text for token in tokens)})
    ranges = [
        token_range
        for leaf in _positive_leaves(normalize(query), negated=False)
        for token_range in occurrences(leaf, document, tokenizer=active).get(field, [])
    ]
    window, highlights = snippet_window(clean, tokens, ranges)
    return Snippet(field, window, highlights)


def _positive_leaves(node: Node, negated: bool) -> Iterator[Term | Phrase]:
    if isinstance(node, Not):
        yield from _positive_leaves(node.operand, not negated)
    elif isinstance(node, (And, Or)):
        for operand in node.operands:
            yield from _positive_leaves(operand, negated)
    elif negated:
        return
    elif isinstance(node, Near):
        yield from node.scoped_operands()
    else:
        yield node


def _merge_overlapping(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, stop in ranges:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return merged
