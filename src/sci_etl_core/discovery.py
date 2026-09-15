"""The read-model a presentation layer renders: plain, immutable dataclasses.

Importing this module loads no store, no event-loop machinery, and no optional
dependency, so a thin UI can depend on it alone. The graph, hit, and chip types
it refers to are annotations only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_etl_core.search.fusion import FusedHit
    from sci_etl_core.search.graph import DiscoveryGraph
    from sci_etl_core.search.query import QueryChip


@dataclass(frozen=True, slots=True)
class Facet:
    """Matching-document counts for the values of one metadata key.

    ``counts`` holds ``(value, count)`` pairs sorted by count descending, then
    value, as ``AsyncTextSearchStore.facet_counts`` returns them: each count
    ignores filters on this key, so it tells what selecting the value would give.
    """

    key: str
    counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Everything a UI needs to render one search, in render-agnostic form.

    ``chips`` describe the parsed query, and ``hits`` are the fused results,
    best first. ``graph`` is the discovery graph around a selected record, or
    ``None``; whether its communities converged is on the graph itself.
    ``total_matched`` counts the records satisfying the query and filters, not
    only the hits shown. ``degraded`` names retrieval legs that failed, such as
    ``("semantic",)`` when the embedding service was unreachable, and
    ``skipped`` names legs that had nothing to run, such as a semantic leg for a
    query of prefix terms only. A UI must tell the user about both rather than
    silently showing weaker results.
    """

    query_text: str
    chips: tuple[QueryChip, ...]
    hits: tuple[FusedHit, ...]
    graph: DiscoveryGraph | None
    facets: tuple[Facet, ...]
    total_matched: int
    elapsed_ms: float
    degraded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
