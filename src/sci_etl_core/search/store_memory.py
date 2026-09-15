from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from sci_etl_core.search.compile_fts5 import require_rankable
from sci_etl_core.search.evaluate import TokenizedDocument, matches, occurrences
from sci_etl_core.search.filters import (
    SNIPPET_ELLIPSIS,
    SNIPPET_TOKENS,
    MetadataFilter,
    encode_metadata,
    matches_filters,
    sanitize_text,
    tag_rows,
    validate_facet_keys,
    validate_filters,
)
from sci_etl_core.search.query import FIELDS, And, Node, Not, Or, Phrase, Term, normalize
from sci_etl_core.search.store_base import AsyncTextSearchStore, BM25Weights, SearchDocument, TextHit
from sci_etl_core.search.tokenize import Token, Tokenizer, Unicode61Tokenizer

BM25_K1 = 1.2
BM25_B = 0.75
BM25_MIN_IDF = 1e-6

_Hits = dict[str, list[tuple[int, int]]]


@dataclass(frozen=True, slots=True)
class _Entry:
    record_id: str
    fields: dict[str, str]
    encoded_metadata: str
    metadata: dict[str, Any]
    tokens: dict[str, list[Token]]
    tokenized: TokenizedDocument
    length: int
    tags: frozenset[tuple[str, str]]


class InMemoryTextSearchStore(AsyncTextSearchStore):
    """Non-persistent lexical index backed by a dict, ranked as SQLite FTS5 ranks.

    Documents are tokenized once, when indexed, by ``tokenizer`` (by default
    :class:`~sci_etl_core.search.tokenize.Unicode61Tokenizer`, which reproduces
    FTS5's own tokenizer). Matching follows
    :func:`~sci_etl_core.search.evaluate.matches`, so with the default tokenizer
    the store matches, filters, and counts exactly the records
    :class:`~sci_etl_core.search.store_sqlite_fts5.AsyncSqliteFts5Store` does,
    which makes it both an offline test double and a check on that store.

    Scores follow FTS5's ``bm25()`` formula: ``k1`` of 1.2, ``b`` of 0.75, an IDF
    floored at ``1e-6``, and the field ``weights``. A word counts towards the
    score, and is highlighted, only where the part of the query holding it
    matches the document: an ``OR`` alternative or an ``AND`` group that does not
    match, and anything negated, adds nothing. FTS5 applies the same rule in
    most cases but not all: whether it counts a word inside a part of the query
    that fails to match depends on the state of its internal iterators, so for
    such queries the two stores can score, and so order, the same records
    differently.

    A snippet is taken from the field with the most counted matches, with ties
    going to ``title``, then ``abstract``, then ``body``.
    """

    def __init__(
        self,
        *,
        facet_keys: Iterable[str] = (),
        weights: BM25Weights | None = None,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        self._facet_keys = frozenset(facet_keys)
        self._weights = BM25Weights() if weights is None else weights
        self._tokenizer = Unicode61Tokenizer() if tokenizer is None else tokenizer
        self._entries: dict[str, _Entry] = {}

    @property
    def facet_keys(self) -> frozenset[str]:
        return self._facet_keys

    async def index(self, documents: Sequence[SearchDocument]) -> None:
        for document in documents:
            self._entries[document.record_id] = self._entry(document)

    async def delete_record(self, record_id: str) -> None:
        self._entries.pop(record_id, None)

    async def search(
        self,
        query: Node,
        limit: int = 20,
        exclude_record_id: str | None = None,
        filters: Sequence[MetadataFilter] = (),
    ) -> list[TextHit]:
        validate_filters(filters, self._facet_keys)
        require_rankable(query)
        if limit < 1:
            return []
        node = normalize(query)
        matched = [entry for entry in self._matching(node, filters) if entry.record_id != exclude_record_id]
        if not matched:
            return []
        leaves = list(_leaves(node))
        idf = self._inverse_document_frequencies(leaves)
        average_length = max(sum(entry.length for entry in self._entries.values()), 1) / len(self._entries)
        hits = [self._hit(entry, node, leaves, idf, average_length) for entry in matched]
        hits.sort(key=lambda hit: (-hit.score, hit.record_id))
        return hits[:limit]

    async def filter_ids(
        self, query: Node | None = None, filters: Sequence[MetadataFilter] = ()
    ) -> frozenset[str]:
        validate_filters(filters, self._facet_keys)
        node = None if query is None else normalize(query)
        return frozenset(entry.record_id for entry in self._matching(node, filters))

    async def get_documents(self, record_ids: Collection[str]) -> dict[str, SearchDocument]:
        return {
            record_id: SearchDocument(record_id, **entry.fields, metadata=json.loads(entry.encoded_metadata))
            for record_id in record_ids
            if (entry := self._entries.get(record_id)) is not None
        }

    async def facet_counts(
        self,
        keys: Sequence[str],
        *,
        query: Node | None = None,
        filters: Sequence[MetadataFilter] = (),
    ) -> dict[str, tuple[tuple[str, int], ...]]:
        validate_filters(filters, self._facet_keys)
        validate_facet_keys(keys, self._facet_keys)
        node = None if query is None else normalize(query)
        counts: dict[str, tuple[tuple[str, int], ...]] = {}
        for key in keys:
            others = [metadata_filter for metadata_filter in filters if metadata_filter.key != key]
            tally = Counter(
                value
                for entry in self._matching(node, others)
                for tag_key, value in entry.tags
                if tag_key == key
            )
            counts[key] = tuple(sorted(tally.items(), key=lambda item: (-item[1], item[0])))
        return counts

    async def count(self) -> int:
        return len(self._entries)

    def _entry(self, document: SearchDocument) -> _Entry:
        fields = {name: sanitize_text(getattr(document, name)) for name in FIELDS}
        tokens = {name: self._tokenizer.tokens(text) for name, text in fields.items()}
        encoded = encode_metadata(document.metadata)
        metadata = json.loads(encoded)
        return _Entry(
            record_id=document.record_id,
            fields=fields,
            encoded_metadata=encoded,
            metadata=metadata,
            tokens=tokens,
            tokenized=TokenizedDocument(*(tuple(token.text for token in tokens[name]) for name in FIELDS)),
            length=sum(len(field_tokens) for field_tokens in tokens.values()),
            tags=frozenset(tag_rows(metadata, self._facet_keys)),
        )

    def _matching(self, node: Node | None, filters: Sequence[MetadataFilter]) -> Iterator[_Entry]:
        for entry in self._entries.values():
            if node is not None and not matches(node, entry.tokenized, tokenizer=self._tokenizer):
                continue
            if matches_filters(entry.metadata, filters):
                yield entry

    def _inverse_document_frequencies(self, leaves: list[Term | Phrase]) -> list[float]:
        rows = len(self._entries)
        frequencies: list[float] = []
        for leaf in leaves:
            containing = sum(
                1 for entry in self._entries.values() if occurrences(leaf, entry.tokenized, tokenizer=self._tokenizer)
            )
            idf = math.log((rows - containing + 0.5) / (containing + 0.5))
            frequencies.append(idf if idf > 0.0 else BM25_MIN_IDF)
        return frequencies

    def _hit(
        self, entry: _Entry, node: Node, leaves: list[Term | Phrase], idf: list[float], average_length: float
    ) -> TextHit:
        found = [occurrences(leaf, entry.tokenized, tokenizer=self._tokenizer) for leaf in leaves]
        _, counted = _counted_hits(node, iter(found))
        saturation = BM25_K1 * (1 - BM25_B + BM25_B * entry.length / average_length)
        score = 0.0
        highlighted: _Hits = {name: [] for name in FIELDS}
        for hits, leaf_idf in zip(counted, idf, strict=True):
            frequency = sum(getattr(self._weights, name) * len(ranges) for name, ranges in hits.items())
            score += leaf_idf * ((frequency * (BM25_K1 + 1)) / (frequency + saturation))
            for name, ranges in hits.items():
                highlighted[name].extend(ranges)
        best = max(FIELDS, key=lambda name: (len(highlighted[name]), -FIELDS.index(name)))
        snippet, highlights = _snippet(entry.fields[best], entry.tokens[best], highlighted[best])
        return TextHit(entry.record_id, score, snippet, highlights, dict(entry.metadata), entry.fields["title"])


def _leaves(node: Node) -> Iterator[Term | Phrase]:
    if isinstance(node, Not):
        yield from _leaves(node.operand)
    elif isinstance(node, (And, Or)):
        for operand in node.operands:
            yield from _leaves(operand)
    else:
        yield node


def _counted_hits(node: Node, found: Iterator[_Hits]) -> tuple[bool, list[_Hits]]:
    if isinstance(node, (Term, Phrase)):
        hits = next(found)
        return bool(hits), [hits]
    if isinstance(node, Not):
        operand_matched, operand_hits = _counted_hits(node.operand, found)
        return not operand_matched, [{} for _ in operand_hits]
    parts = [_counted_hits(operand, found) for operand in node.operands]
    if isinstance(node, And):
        matched = all(part_matched for part_matched, _ in parts)
        return matched, [hits if matched else {} for _, part_hits in parts for hits in part_hits]
    matched = any(part_matched for part_matched, _ in parts)
    return matched, [hits if part_matched else {} for part_matched, part_hits in parts for hits in part_hits]


def _snippet(
    text: str, tokens: list[Token], ranges: list[tuple[int, int]]
) -> tuple[str, tuple[tuple[int, int], ...]]:
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


def _merge_overlapping(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, stop in ranges:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return merged
