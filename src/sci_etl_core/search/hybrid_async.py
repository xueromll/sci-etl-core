from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from sci_etl_core.exceptions import EmbeddingError, SearchQueryError
from sci_etl_core.search.filters import SearchFilter, validate_filters
from sci_etl_core.search.fusion import FusedHit, FusionParams, FusionStrategy, reciprocal_rank_fusion
from sci_etl_core.search.parser import parse_ranked_query, parse_semantic_query
from sci_etl_core.search.query import Node, semantic_text
from sci_etl_core.search.snippets import passage_snippet
from sci_etl_core.search.store_base import AsyncTextSearchStore, SearchDocument, TextHit

if TYPE_CHECKING:
    from sci_etl_core.embeddings.finder_async import AsyncSimilarArticleFinder
    from sci_etl_core.embeddings.store_base import SearchHit

SearchMode = Literal["lexical", "semantic", "hybrid"]
"""Which retrieval legs :meth:`AsyncHybridSearcher.search` runs."""

SEARCH_MODES: tuple[str, ...] = ("lexical", "semantic", "hybrid")
"""Every :data:`SearchMode`, for checking a mode that arrives as plain text."""

@dataclass(frozen=True, slots=True)
class HybridParams:
    """How many candidates each retrieval leg fetches before fusion.

    Each leg fetches ``candidate_pool`` records, and never fewer than the
    ``top_k`` asked for, so a record ranked #40 lexically and #3 semantically
    can still reach the top 20.

    The semantic leg asks the vector memory for ``candidate_pool ×
    chunk_pool_factor`` chunks and keeps each record's best chunk. It yields
    ``candidate_pool`` distinct records whenever those chunks span at least that
    many records, that is, when records contribute on average no more than
    ``chunk_pool_factor`` chunks to that prefix of the chunk ranking. When a few
    long records dominate the top chunks, fewer records are returned. The
    searcher does not retry, because a retry would call the embedder again for
    the same text. Raise the factor for corpora of long documents.

    Raises:
        ValueError: ``candidate_pool`` or ``chunk_pool_factor`` is less than 1.
    """

    candidate_pool: int = 100
    chunk_pool_factor: int = 5

    def __post_init__(self) -> None:
        if self.candidate_pool < 1:
            raise ValueError(f"candidate_pool must be at least 1, not {self.candidate_pool!r}")
        if self.chunk_pool_factor < 1:
            raise ValueError(f"chunk_pool_factor must be at least 1, not {self.chunk_pool_factor!r}")


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """The fused hits of one search, and which retrieval legs did not contribute.

    ``degraded`` names the legs that were attempted and failed, such as
    ``"semantic"`` when the embedding service was unreachable. ``skipped`` names
    the legs that had nothing to run, such as a semantic leg without a finder or
    for a query made only of prefix terms. A UI words the two differently.
    """

    hits: list[FusedHit] = field(default_factory=list)
    degraded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


class AsyncHybridSearcher:
    """Search the corpus by Boolean query, by meaning, or by both at once.

    ``mode="lexical"`` ranks documents by BM25 in the text index.
    ``mode="semantic"`` ranks whole articles by their best-matching chunk in the
    vector memory. ``mode="hybrid"`` runs both at once and fuses the two
    rankings with ``strategy``, by default reciprocal rank fusion.

    The query is parsed once, before any I/O. The semantic leg embeds
    :func:`~sci_etl_core.search.query.semantic_text` of the query, so operators,
    field scopes, negated terms, and prefix terms never reach the embedder.
    Metadata ``filters`` apply to both legs: the lexical leg filters inside the
    index, and the semantic leg's candidates are narrowed to the records passing
    the filters before fusion, so a filtered-out record never takes a slot.

    A hybrid search whose semantic leg raises
    :class:`~sci_etl_core.exceptions.EmbeddingError` falls back to the lexical
    results, logs the failure, and reports it in :attr:`SearchOutcome.degraded`.
    A lexical failure is never swallowed, because it means the local index is
    broken.

    The searcher never closes; the caller that constructed the stores closes
    them.
    """

    def __init__(
        self,
        text_store: AsyncTextSearchStore,
        finder: AsyncSimilarArticleFinder | None = None,
        *,
        strategy: FusionStrategy = reciprocal_rank_fusion,
        params: HybridParams | None = None,
        fusion: FusionParams | None = None,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        """Configure the searcher; ``finder`` may be ``None`` to search the text index alone.

        Without a finder, a hybrid search runs the lexical leg alone and reports
        the semantic leg in :attr:`SearchOutcome.skipped`, not in ``degraded``,
        and a semantic search raises
        :class:`~sci_etl_core.exceptions.SearchQueryError`.

        ``fusion.weights``, when given, weighs the lexical and the semantic list,
        in that order. ``logger`` receives the line logged when a hybrid search
        falls back to lexical results.

        Raises:
            ValueError: ``fusion.weights`` does not hold exactly two weights.
        """
        self._fusion = FusionParams() if fusion is None else fusion
        if self._fusion.weights is not None and len(self._fusion.weights) != 2:
            raise ValueError("fusion.weights must hold two weights: the lexical one, then the semantic one")
        self._text_store = text_store
        self._finder = finder
        self._strategy = strategy
        self._params = HybridParams() if params is None else params
        self._log = logger or (lambda _msg: None)

    async def search(
        self,
        query: str,
        top_k: int = 20,
        *,
        mode: SearchMode = "hybrid",
        filters: Sequence[SearchFilter] = (),
    ) -> SearchOutcome:
        """Return the ``top_k`` best records for ``query``, fused across the legs ``mode`` runs.

        Every error below except the last two is raised before any I/O. A
        ``top_k`` below 1 returns no hits.

        A hit the lexical leg found carries its snippets and highlights. A hit
        only the semantic leg found takes its title and metadata from the text
        index, or from its best chunk's metadata when the index does not hold
        the record, and its snippet from that chunk, with the query's words
        highlighted where they occur in it
        (:func:`~sci_etl_core.search.snippets.passage_snippet`).

        Raises:
            ValueError: ``mode`` is unknown, or ``filters`` holds two filters on
                one key or a key outside the text store's facet keys.
            SearchQueryError: The query is malformed or cannot be ranked, such
                as a pure negation; ``text_store.filter_ids`` answers those. In
                semantic mode, also when there is no finder, or when the query
                has no whole word to embed.
            EmbeddingError: The semantic leg failed in ``mode="semantic"``.
            SearchStoreError: The text index cannot be read.
        """
        if mode not in SEARCH_MODES:
            raise ValueError(f"Unknown search mode {mode!r}; expected one of {', '.join(SEARCH_MODES)}")
        validate_filters(filters, self._text_store.facet_keys)
        node, meaning = self._parse(query, mode)
        skipped = ("semantic",) if mode == "hybrid" and not meaning else ()
        if top_k < 1:
            return SearchOutcome(skipped=skipped)
        pool = max(self._params.candidate_pool, top_k)

        legs: dict[str, Awaitable[Any]] = {}
        if mode != "semantic":
            legs["lexical"] = self._text_store.search(node, pool, filters=filters)
        if meaning and self._finder is not None:
            legs["semantic"] = self._finder.find_best_chunks(
                meaning, top_k=pool, chunk_pool=pool * self._params.chunk_pool_factor
            )
            if filters:
                legs["allowed"] = self._text_store.filter_ids(None, filters)
        results: dict[str, Any] = dict(
            zip(legs, await asyncio.gather(*legs.values(), return_exceptions=True), strict=True)
        )

        for name in ("lexical", "allowed"):
            if isinstance(results.get(name), BaseException):
                raise results[name]
        degraded: tuple[str, ...] = ()
        articles = results.get("semantic")
        if isinstance(articles, EmbeddingError) and mode == "hybrid":
            self._log(f"Semantic search failed; showing lexical results only: {articles!r}")
            degraded = ("semantic",)
            articles = None
        elif isinstance(articles, BaseException):
            raise articles

        lexical_hits: list[TextHit] | None = results.get("lexical")
        allowed: frozenset[str] | None = results.get("allowed")
        semantic: list[SearchHit] | None = None
        if articles is not None:
            semantic = [article for article in articles if allowed is None or article.record_id in allowed]
        hits = await self._fuse(node, lexical_hits, semantic, top_k)
        return SearchOutcome(hits, degraded, skipped)

    def _parse(self, query: str, mode: str) -> tuple[Node, str]:
        if mode == "lexical":
            return parse_ranked_query(query), ""
        if mode == "semantic":
            node, meaning = parse_semantic_query(query)
            if self._finder is None:
                raise SearchQueryError("Semantic mode requires a finder")
            return node, meaning
        node = parse_ranked_query(query)
        return node, semantic_text(node) if self._finder is not None else ""

    async def _fuse(
        self, node: Node, lexical_hits: list[TextHit] | None, semantic: list[SearchHit] | None, top_k: int
    ) -> list[FusedHit]:
        ranked_lists: list[list[tuple[str, float]]] = []
        leg_indexes: list[int] = []
        if lexical_hits is not None:
            ranked_lists.append([(hit.record_id, hit.score) for hit in lexical_hits])
            leg_indexes.append(0)
        if semantic is not None:
            ranked_lists.append([(article.record_id, article.score) for article in semantic])
            leg_indexes.append(1)
        fusion = self._fusion
        if fusion.weights is not None:
            fusion = FusionParams(fusion.k, tuple(fusion.weights[index] for index in leg_indexes))
        fused = self._strategy(ranked_lists, fusion)[:top_k]

        lexical = {hit.record_id: (rank, hit) for rank, hit in enumerate(lexical_hits or [], start=1)}
        semantic_ranks = {article.record_id: (rank, article) for rank, article in enumerate(semantic or [], start=1)}
        missing = [record_id for record_id, _score in fused if record_id not in lexical]
        documents = await self._text_store.get_documents(missing) if missing else {}
        return [_fused_hit(node, record_id, score, lexical, semantic_ranks, documents) for record_id, score in fused]


def _fused_hit(
    node: Node,
    record_id: str,
    score: float,
    lexical: dict[str, tuple[int, TextHit]],
    semantic: dict[str, tuple[int, SearchHit]],
    documents: dict[str, SearchDocument],
) -> FusedHit:
    semantic_rank = semantic[record_id][0] if record_id in semantic else None
    if record_id in lexical:
        rank, hit = lexical[record_id]
        return FusedHit(
            record_id, score, rank, semantic_rank, hit.snippet, hit.highlights, hit.metadata, hit.title, hit.snippets
        )
    chunk = semantic[record_id][1]
    passage = passage_snippet(node, chunk.text)
    document = documents.get(record_id)
    if document is not None:
        metadata, title = document.metadata, document.title
    else:
        chunk_title = chunk.metadata.get("title")
        metadata, title = dict(chunk.metadata), chunk_title if isinstance(chunk_title, str) else ""
    return FusedHit(
        record_id, score, None, semantic_rank, passage.text, passage.highlights, metadata, title, (passage,)
    )
