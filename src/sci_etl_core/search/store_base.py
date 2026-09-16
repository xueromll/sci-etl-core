from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sci_etl_core.search.filters import validate_facet_keys, validate_filters

if TYPE_CHECKING:
    from sci_etl_core.search.filters import RangeFilter, SearchFilter
    from sci_etl_core.search.query import Node


@dataclass(slots=True)
class SearchDocument:
    """One article's searchable text, as a single indexable unit.

    The lexical index holds one document per record, while the vector memory
    holds one row per chunk. BM25 saturates on term frequency and normalizes by
    document length, so chunking a document would fragment its statistics and
    inflate short chunks.

    ``metadata`` is stored as JSON and reads back as JSON: a ``datetime`` put in
    comes back as its ISO 8601 string. Field types are not enforced.
    :class:`~sci_etl_core.search.filters.MetadataFilter` matches exact values,
    and :class:`~sci_etl_core.search.filters.RangeFilter` ranges of integers or
    of text such as ISO 8601 dates.
    """

    record_id: str
    title: str = ""
    abstract: str = ""
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Snippet:
    """A passage of one field, with the matched words marked.

    ``field`` is one of :data:`~sci_etl_core.search.query.FIELDS`. ``text`` is
    plain text of at most :data:`~sci_etl_core.search.filters.SNIPPET_TOKENS`
    tokens, starting or ending with
    :data:`~sci_etl_core.search.filters.SNIPPET_ELLIPSIS` where the field goes
    on, and ``highlights`` are half-open ``[start, end)`` character offsets into
    ``text``.
    """

    field: str
    text: str
    highlights: tuple[tuple[int, int], ...] = ()


@dataclass(slots=True)
class TextHit:
    """A document returned from a Boolean query, with its lexical score.

    ``score`` is higher for a better match, and is never the raw negative value
    SQLite's ``bm25()`` returns. Its scale depends on the corpus, so compare
    scores only within one result list. ``snippet`` is plain text from the
    field matching best, and ``highlights`` are half-open ``[start, end)``
    character offsets into it covering the matched words, so a UI applies its
    own markup. ``snippets`` holds one :class:`Snippet` for every field with a
    highlighted match, in :data:`~sci_etl_core.search.query.FIELDS` order, so a
    UI can show a match in the title and one in the body together. ``title``
    and ``metadata`` are the document's, as the store reads them back.
    """

    record_id: str
    score: float
    snippet: str = ""
    highlights: tuple[tuple[int, int], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    snippets: tuple[Snippet, ...] = ()


@dataclass(frozen=True, slots=True)
class BM25Weights:
    """How much a match in each field counts towards a document's BM25 score.

    Raises:
        ValueError: A weight is negative or not finite.
    """

    title: float = 10.0
    abstract: float = 4.0
    body: float = 1.0

    def __post_init__(self) -> None:
        for name in ("title", "abstract", "body"):
            weight = getattr(self, name)
            if not math.isfinite(weight) or weight < 0:
                raise ValueError(f"The {name} weight must be a finite number that is not negative, not {weight!r}")


class AsyncTextSearchStore(ABC):
    """An accumulating lexical index of articles, searchable by Boolean query.

    The index is per record, while the vector memory is per chunk (see
    :class:`SearchDocument`), so lexical and semantic results are fused at the
    record level.

    Queries arrive as parsed, normalized ASTs, never as text: a store never
    parses, so no backend can invent its own dialect. Metadata filters apply to
    the keys in :attr:`facet_keys` only, and a filter or facet on any other key
    raises :class:`ValueError` before any I/O.
    """

    @property
    @abstractmethod
    def facet_keys(self) -> frozenset[str]:
        """The metadata keys this store tags documents by, for filters and facets."""

    @abstractmethod
    async def index(self, documents: Sequence[SearchDocument]) -> None:
        """Store ``documents``, replacing any stored document with the same ``record_id``.

        Control characters other than tab and line breaks are stored as spaces.
        When ``documents`` repeats a ``record_id``, the last one is kept.
        """

    @abstractmethod
    async def delete_record(self, record_id: str) -> None:
        """Remove the document of ``record_id``, if one is stored."""

    async def replace_record(self, document: SearchDocument) -> None:
        """Make ``document`` the stored document of its record.

        The default deletes and then indexes; a backend that can upsert
        atomically should override it.
        """
        await self.delete_record(document.record_id)
        await self.index([document])

    @abstractmethod
    async def search(
        self,
        query: Node,
        limit: int = 20,
        exclude_record_id: str | None = None,
        filters: Sequence[SearchFilter] = (),
    ) -> list[TextHit]:
        """Rank the documents matching ``query`` and ``filters`` by BM25, best first.

        Equal scores are ordered by ``record_id``. ``filters`` apply before
        ``limit``, so a filtered search still returns up to ``limit`` hits.
        A ``limit`` below 1 returns no hits.

        Raises:
            ValueError: A filter's key is not in :attr:`facet_keys`, or two
                filters share a key.
            SearchQueryError: ``query`` is not rankable, such as a pure
                negation (:func:`~sci_etl_core.search.compile_fts5.is_rankable`).
            SearchStoreError: The index cannot be read, or a filter's key has no
                built tags yet (see ``AsyncSqliteFts5Store.rebuild_tags``).
        """

    @abstractmethod
    async def filter_ids(
        self, query: Node | None = None, filters: Sequence[SearchFilter] = ()
    ) -> frozenset[str]:
        """Return every record satisfying ``query`` and ``filters``, in no order.

        Any query is accepted, including a pure negation, which is why the
        result carries no order. ``query=None`` matches every document.

        Raises:
            ValueError: A filter's key is not in :attr:`facet_keys`, or two
                filters share a key.
            SearchStoreError: The index cannot be read, or a filter's key has no
                built tags yet (see ``AsyncSqliteFts5Store.rebuild_tags``).
        """

    @abstractmethod
    async def get_documents(self, record_ids: Collection[str]) -> dict[str, SearchDocument]:
        """Return the stored documents for ``record_ids``; unknown ids are omitted."""

    @abstractmethod
    async def facet_counts(
        self,
        keys: Sequence[str],
        *,
        query: Node | None = None,
        filters: Sequence[SearchFilter] = (),
    ) -> dict[str, tuple[tuple[str, int], ...]]:
        """Count matching documents per value of each facet key.

        For each ``key``, documents are counted when they satisfy ``query`` and
        every filter whose key is *not* ``key``; filters on ``key`` itself are
        ignored for that key's counts. Each count answers "how many results
        would this value give if it were selected instead". When ``filters``
        has no filter on ``key``, the exclusion is a no-op, and that key's
        counts are over the full match set of ``query`` and every other key's
        filter. Values are sorted by count descending, then value ascending.
        Values with a count of 0 are omitted from the returned tuple, and a key
        with no matching value maps to an empty tuple.

        Raises:
            ValueError: A key in ``keys`` or ``filters`` is not in
                :attr:`facet_keys`, or two filters in ``filters`` share a key.
            SearchStoreError: The index cannot be read, or a key in ``keys`` or
                ``filters`` has no built tags yet (see
                ``AsyncSqliteFts5Store.rebuild_tags``).
        """

    async def range_counts(
        self,
        ranges: Sequence[RangeFilter],
        *,
        query: Node | None = None,
        filters: Sequence[SearchFilter] = (),
    ) -> tuple[int, ...]:
        """Count matching documents inside each of ``ranges``, in the order given.

        Each count is of the documents satisfying ``query``, the range, and every
        filter whose key is not the range's key, so a count answers "how many
        results would this range give if it were selected instead", as
        :meth:`facet_counts` does for exact values. Ranges may share a key and
        overlap, as buckets of a histogram or presets such as "last 5 years" do,
        and a negated range counts the documents outside it.

        The default runs :meth:`filter_ids` once per range; a backend that can
        count in one read should override it.

        Raises:
            ValueError: A key in ``ranges`` or ``filters`` is not in
                :attr:`facet_keys`, or two filters in ``filters`` share a key.
            SearchStoreError: The index cannot be read, or a key has no built
                tags yet (see ``AsyncSqliteFts5Store.rebuild_tags``).
        """
        validate_filters(filters, self.facet_keys)
        validate_facet_keys([search_range.key for search_range in ranges], self.facet_keys)
        counts: list[int] = []
        for search_range in ranges:
            others = [search_filter for search_filter in filters if search_filter.key != search_range.key]
            counts.append(len(await self.filter_ids(query, [*others, search_range])))
        return tuple(counts)

    @abstractmethod
    async def count(self) -> int:
        """Return the number of stored documents."""

    async def aclose(self) -> None:
        """Release any held resources. No-op by default."""
        return None
