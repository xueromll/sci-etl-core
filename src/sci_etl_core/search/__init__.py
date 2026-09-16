from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "BackfillReport": "sci_etl_core.search.backfill_async",
    "backfill_text_index": "sci_etl_core.search.backfill_async",
    "merge_passages": "sci_etl_core.search.backfill_async",
    "stored_record_document": "sci_etl_core.search.backfill_async",
    "FILTER_LEAF": "sci_etl_core.search.compile_fts5",
    "is_rankable": "sci_etl_core.search.compile_fts5",
    "require_rankable": "sci_etl_core.search.compile_fts5",
    "to_filter_expression": "sci_etl_core.search.compile_fts5",
    "to_match_expression": "sci_etl_core.search.compile_fts5",
    "AsyncEdgeSource": "sci_etl_core.search.edges",
    "EmbeddingEdgeSource": "sci_etl_core.search.edges",
    "MetadataEdgeSource": "sci_etl_core.search.edges",
    "TokenizedDocument": "sci_etl_core.search.evaluate",
    "matches": "sci_etl_core.search.evaluate",
    "occurrences": "sci_etl_core.search.evaluate",
    "MetadataFilter": "sci_etl_core.search.filters",
    "RangeFilter": "sci_etl_core.search.filters",
    "SearchFilter": "sci_etl_core.search.filters",
    "SNIPPET_CLOSE": "sci_etl_core.search.filters",
    "SNIPPET_ELLIPSIS": "sci_etl_core.search.filters",
    "SNIPPET_OPEN": "sci_etl_core.search.filters",
    "SNIPPET_TOKENS": "sci_etl_core.search.filters",
    "encode_metadata": "sci_etl_core.search.filters",
    "matches_filters": "sci_etl_core.search.filters",
    "sanitize_text": "sci_etl_core.search.filters",
    "split_markers": "sci_etl_core.search.filters",
    "tag_in_range": "sci_etl_core.search.filters",
    "tag_rows": "sci_etl_core.search.filters",
    "validate_facet_keys": "sci_etl_core.search.filters",
    "validate_filters": "sci_etl_core.search.filters",
    "FusedHit": "sci_etl_core.search.fusion",
    "FusionParams": "sci_etl_core.search.fusion",
    "FusionStrategy": "sci_etl_core.search.fusion",
    "normalized_score_fusion": "sci_etl_core.search.fusion",
    "reciprocal_rank_fusion": "sci_etl_core.search.fusion",
    "DiscoveryGraph": "sci_etl_core.search.graph",
    "GraphEdge": "sci_etl_core.search.graph",
    "GraphNode": "sci_etl_core.search.graph",
    "GraphParams": "sci_etl_core.search.graph",
    "build_discovery_graph": "sci_etl_core.search.graph",
    "filter_graph": "sci_etl_core.search.graph",
    "label_communities": "sci_etl_core.search.graph",
    "select_edges": "sci_etl_core.search.graph",
    "SEARCH_MODES": "sci_etl_core.search.hybrid_async",
    "AsyncHybridSearcher": "sci_etl_core.search.hybrid_async",
    "HybridParams": "sci_etl_core.search.hybrid_async",
    "SearchMode": "sci_etl_core.search.hybrid_async",
    "SearchOutcome": "sci_etl_core.search.hybrid_async",
    "AsyncSearchIndexer": "sci_etl_core.search.index_async",
    "parse_query": "sci_etl_core.search.parser",
    "parse_ranked_query": "sci_etl_core.search.parser",
    "parse_semantic_query": "sci_etl_core.search.parser",
    "FIELDS": "sci_etl_core.search.query",
    "NEAR_DISTANCE": "sci_etl_core.search.query",
    "And": "sci_etl_core.search.query",
    "Near": "sci_etl_core.search.query",
    "Node": "sci_etl_core.search.query",
    "Not": "sci_etl_core.search.query",
    "Or": "sci_etl_core.search.query",
    "Phrase": "sci_etl_core.search.query",
    "QueryChip": "sci_etl_core.search.query",
    "Term": "sci_etl_core.search.query",
    "describe": "sci_etl_core.search.query",
    "normalize": "sci_etl_core.search.query",
    "semantic_text": "sci_etl_core.search.query",
    "passage_snippet": "sci_etl_core.search.snippets",
    "snippet_window": "sci_etl_core.search.snippets",
    "AsyncTextSearchStore": "sci_etl_core.search.store_base",
    "BM25Weights": "sci_etl_core.search.store_base",
    "SearchDocument": "sci_etl_core.search.store_base",
    "Snippet": "sci_etl_core.search.store_base",
    "TextHit": "sci_etl_core.search.store_base",
    "InMemoryTextSearchStore": "sci_etl_core.search.store_memory",
    "AsyncSqliteFts5Store": "sci_etl_core.search.store_sqlite_fts5",
    "fts5_available": "sci_etl_core.search.store_sqlite_fts5",
    "Token": "sci_etl_core.search.tokenize",
    "Tokenizer": "sci_etl_core.search.tokenize",
    "Unicode61Tokenizer": "sci_etl_core.search.tokenize",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.search.backfill_async import (
        BackfillReport,
        backfill_text_index,
        merge_passages,
        stored_record_document,
    )
    from sci_etl_core.search.compile_fts5 import (
        FILTER_LEAF,
        is_rankable,
        require_rankable,
        to_filter_expression,
        to_match_expression,
    )
    from sci_etl_core.search.edges import AsyncEdgeSource, EmbeddingEdgeSource, MetadataEdgeSource
    from sci_etl_core.search.evaluate import TokenizedDocument, matches, occurrences
    from sci_etl_core.search.filters import (
        SNIPPET_CLOSE,
        SNIPPET_ELLIPSIS,
        SNIPPET_OPEN,
        SNIPPET_TOKENS,
        MetadataFilter,
        RangeFilter,
        SearchFilter,
        encode_metadata,
        matches_filters,
        sanitize_text,
        split_markers,
        tag_in_range,
        tag_rows,
        validate_facet_keys,
        validate_filters,
    )
    from sci_etl_core.search.fusion import (
        FusedHit,
        FusionParams,
        FusionStrategy,
        normalized_score_fusion,
        reciprocal_rank_fusion,
    )
    from sci_etl_core.search.graph import (
        DiscoveryGraph,
        GraphEdge,
        GraphNode,
        GraphParams,
        build_discovery_graph,
        filter_graph,
        label_communities,
        select_edges,
    )
    from sci_etl_core.search.hybrid_async import (
        SEARCH_MODES,
        AsyncHybridSearcher,
        HybridParams,
        SearchMode,
        SearchOutcome,
    )
    from sci_etl_core.search.index_async import AsyncSearchIndexer
    from sci_etl_core.search.parser import parse_query, parse_ranked_query, parse_semantic_query
    from sci_etl_core.search.query import (
        FIELDS,
        NEAR_DISTANCE,
        And,
        Near,
        Node,
        Not,
        Or,
        Phrase,
        QueryChip,
        Term,
        describe,
        normalize,
        semantic_text,
    )
    from sci_etl_core.search.snippets import passage_snippet, snippet_window
    from sci_etl_core.search.store_base import AsyncTextSearchStore, BM25Weights, SearchDocument, Snippet, TextHit
    from sci_etl_core.search.store_memory import InMemoryTextSearchStore
    from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store, fts5_available
    from sci_etl_core.search.tokenize import Token, Tokenizer, Unicode61Tokenizer
