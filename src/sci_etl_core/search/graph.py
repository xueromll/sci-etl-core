from __future__ import annotations

import asyncio
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from sci_etl_core.search.filters import MetadataFilter, matches_filters, validate_filters

if TYPE_CHECKING:
    from sci_etl_core.search.edges import AsyncEdgeSource
    from sci_etl_core.search.store_base import AsyncTextSearchStore

NeighbourLists = dict[str, list[tuple[str, float]]]


@dataclass(frozen=True, slots=True)
class GraphNode:
    """A record in a discovery graph.

    ``degree`` counts the distinct records the node shares an edge with.
    ``community`` is the canonical id :func:`label_communities` assigned.
    ``title`` and ``metadata`` come from the text index, and are empty for a
    record the index does not hold.
    """

    record_id: str
    title: str = ""
    degree: int = 0
    community: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """An undirected weighted edge, with ``source`` sorting before ``target``.

    ``kind`` names the edge source that produced it, such as ``"semantic"``,
    ``"metadata"``, or ``"citation"``.
    """

    source: str
    target: str
    weight: float
    kind: str


@dataclass(frozen=True, slots=True)
class DiscoveryGraph:
    """The neighbourhood of a seed record, as topology only.

    It holds no coordinates, colours, or layout: layout is a rendering concern,
    so a UI runs force-directed layout over this data. ``communities_converged``
    is ``False`` when label propagation stopped at its pass limit, so a UI can
    say the communities are approximate.
    """

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    seed_record_id: str | None
    communities_converged: bool


@dataclass(frozen=True, slots=True)
class GraphParams:
    """How far and how densely a discovery graph grows around its seed.

    The graph grows ``depth`` breadth-first levels. Each record expands to the
    up to ``fanout`` neighbours per edge source whose weight is at least
    ``min_weight``. ``max_nodes`` is a hard cap, checked before each level is
    expanded. With ``mutual_only``, an edge is kept only when each record is
    among the other's ``fanout`` nearest, which keeps a hub record from
    connecting to everything. ``max_iterations`` bounds label propagation.

    Raises:
        ValueError: ``depth`` is negative, ``fanout``, ``max_nodes``, or
            ``max_iterations`` is less than 1, or ``min_weight`` is not finite.
    """

    depth: int = 2
    fanout: int = 8
    min_weight: float = 0.35
    max_nodes: int = 200
    mutual_only: bool = True
    max_iterations: int = 20

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise ValueError(f"depth must not be negative, not {self.depth!r}")
        for name in ("fanout", "max_nodes", "max_iterations"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1, not {getattr(self, name)!r}")
        if not math.isfinite(self.min_weight):
            raise ValueError(f"min_weight must be finite, not {self.min_weight!r}")


def select_edges(
    neighbour_lists: Sequence[tuple[str, Mapping[str, Sequence[tuple[str, float]]]]],
    nodes: Collection[str],
    *,
    min_weight: float,
    mutual_only: bool,
) -> list[GraphEdge]:
    """Turn each edge source's neighbour lists into undirected edges between ``nodes``.

    ``neighbour_lists`` pairs each source's edge kind with its lists, which map a
    record to its nearest records, already cut to the fanout. A record gets an
    edge of that kind to a neighbour in its list when both are in ``nodes``, they
    differ, and the weight is at least ``min_weight``. With ``mutual_only``, the
    record must also be in the neighbour's list. Edges of one kind between one
    pair merge, keeping the heaviest weight. Edges are sorted by source, target,
    and kind.
    """
    members = set(nodes)
    merged: dict[tuple[str, str, str], float] = {}
    for kind, lists in neighbour_lists:
        for record_id, neighbours in lists.items():
            if record_id not in members:
                continue
            for neighbour, weight in neighbours:
                if neighbour not in members or neighbour == record_id or weight < min_weight:
                    continue
                if mutual_only and all(other != record_id for other, _weight in lists.get(neighbour, ())):
                    continue
                key = (min(record_id, neighbour), max(record_id, neighbour), kind)
                merged[key] = max(merged.get(key, weight), weight)
    return [GraphEdge(source, target, weight, kind) for (source, target, kind), weight in sorted(merged.items())]


def label_communities(
    nodes: Sequence[str], edges: Sequence[GraphEdge], *, max_iterations: int = 20
) -> tuple[dict[str, int], bool]:
    """Assign each node a community by label propagation.

    Returns the communities at convergence and ``True``, or, if a pass limit of
    ``max_iterations`` is reached first, the communities after the last pass and
    ``False``. The result does not depend on the order of ``nodes`` or ``edges``:

    1. A pair joined by several edges gets the heaviest weight, in both
       directions. Self-loops and edges touching a record outside ``nodes`` are
       ignored.
    2. Each node starts with its index in sorted ``record_id`` order as its label.
    3. A pass visits nodes in sorted order and updates labels in place. A node
       sums edge weights per neighbouring label, visiting neighbours in sorted
       order, and switches only when the heaviest label's total is strictly
       greater than its current label's; among labels tied for heaviest, it
       takes the lowest.
    4. A pass that changes no label ends the run as converged.
       ``max_iterations`` counts every pass, including that last one.
    5. Communities are numbered 0, 1, 2, … in order of their smallest member.

    Raises:
        ValueError: ``max_iterations`` is less than 1.
    """
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be at least 1, not {max_iterations!r}")
    ordered = sorted(set(nodes))
    label = {record_id: index for index, record_id in enumerate(ordered)}
    adjacency: dict[str, dict[str, float]] = {record_id: {} for record_id in ordered}
    for edge in edges:
        if edge.source in adjacency and edge.target in adjacency and edge.source != edge.target:
            for one, other in ((edge.source, edge.target), (edge.target, edge.source)):
                adjacency[one][other] = max(adjacency[one].get(other, edge.weight), edge.weight)
    converged = False
    for _pass in range(max_iterations):
        changed = False
        for record_id in ordered:
            totals: dict[int, float] = {}
            for neighbour in sorted(adjacency[record_id]):
                totals[label[neighbour]] = totals.get(label[neighbour], 0.0) + adjacency[record_id][neighbour]
            if not totals:
                continue
            heaviest = max(totals.values())
            if heaviest > totals.get(label[record_id], 0.0):
                label[record_id] = min(candidate for candidate, total in totals.items() if total == heaviest)
                changed = True
        if not changed:
            converged = True
            break
    canonical: dict[int, int] = {}
    for record_id in ordered:
        canonical.setdefault(label[record_id], len(canonical))
    return {record_id: canonical[label[record_id]] for record_id in ordered}, converged


def filter_graph(
    graph: DiscoveryGraph,
    *,
    matched_ids: Collection[str] | None = None,
    filters: Sequence[MetadataFilter] = (),
) -> DiscoveryGraph:
    """Keep the nodes whose record is in ``matched_ids`` and whose metadata passes ``filters``.

    The seed is always kept. Edges losing an endpoint are dropped, and degrees
    count the remaining edges; communities are kept as they were, so a UI's
    colours stay stable while filtering. ``matched_ids`` usually comes from the
    text store's ``filter_ids``, which also answers a pure negation, and
    ``filters`` are applied in memory with the same semantics as the stores, so
    a facet toggle needs no I/O.

    Raises:
        ValueError: Two filters share a key.
    """
    validate_filters(filters)
    allowed = None if matched_ids is None else set(matched_ids)
    kept = [
        node
        for node in graph.nodes
        if node.record_id == graph.seed_record_id
        or ((allowed is None or node.record_id in allowed) and matches_filters(node.metadata, filters))
    ]
    kept_ids = {node.record_id for node in kept}
    edges = tuple(edge for edge in graph.edges if edge.source in kept_ids and edge.target in kept_ids)
    degrees = _degrees(edges)
    return DiscoveryGraph(
        tuple(replace(node, degree=degrees.get(node.record_id, 0)) for node in kept),
        edges,
        graph.seed_record_id,
        graph.communities_converged,
    )


async def build_discovery_graph(
    seed_record_id: str,
    sources: Sequence[AsyncEdgeSource],
    text_store: AsyncTextSearchStore,
    *,
    params: GraphParams | None = None,
) -> DiscoveryGraph:
    """Grow the discovery graph around ``seed_record_id``.

    Each breadth-first level issues one batched ``neighbours`` call per source,
    with the sources running concurrently. A record's neighbour lists are fetched
    at most once per build, and reused for the mutual check. When sources fail,
    every source is awaited first, and then the first failure in source order is
    raised. Each source's lists are cleaned before use: a record never neighbours
    itself, a repeated neighbour keeps its heaviest weight, weights that are not
    finite are dropped, and each list is cut to the fanout.

    Edges are chosen by :func:`select_edges`, and only records connected to the
    seed through them are kept; the seed always is. Communities come from
    :func:`label_communities`, and titles and metadata from one
    ``get_documents`` call on ``text_store``.

    A neighbour query costs what the source costs. With an exact-scan vector
    store, a build issues up to one query per node, each scanning every stored
    chunk, so keep ``max_nodes`` small for large memories or use an approximate
    nearest-neighbour store behind the same interface.

    Raises:
        ValueError: ``sources`` is empty.
    """
    active = GraphParams() if params is None else params
    if not sources:
        raise ValueError("build_discovery_graph needs at least one edge source")
    memo: list[NeighbourLists] = [{} for _ in sources]
    nodes = [seed_record_id]
    seen = {seed_record_id}
    frontier = [seed_record_id]
    for _level in range(active.depth):
        if not frontier or len(nodes) >= active.max_nodes:
            break
        await _fetch(sources, memo, frontier, active.fanout)
        next_frontier: list[str] = []
        for record_id in frontier:
            for neighbour in _expansion(memo, record_id, active.min_weight):
                if neighbour not in seen and len(nodes) < active.max_nodes:
                    seen.add(neighbour)
                    nodes.append(neighbour)
                    next_frontier.append(neighbour)
        frontier = next_frontier
    if active.mutual_only:
        await _fetch(sources, memo, nodes, active.fanout)

    candidates = select_edges(
        [(source.kind, lists) for source, lists in zip(sources, memo, strict=True)],
        nodes,
        min_weight=active.min_weight,
        mutual_only=active.mutual_only,
    )
    connected = _connected(seed_record_id, candidates)
    edges = tuple(edge for edge in candidates if edge.source in connected)
    kept = [record_id for record_id in nodes if record_id in connected]
    communities, converged = label_communities(kept, edges, max_iterations=active.max_iterations)
    documents = await text_store.get_documents(kept)
    degrees = _degrees(edges)
    graph_nodes = tuple(
        GraphNode(
            record_id,
            documents[record_id].title if record_id in documents else "",
            degrees.get(record_id, 0),
            communities[record_id],
            documents[record_id].metadata if record_id in documents else {},
        )
        for record_id in kept
    )
    return DiscoveryGraph(graph_nodes, edges, seed_record_id, converged)


async def _fetch(
    sources: Sequence[AsyncEdgeSource], memo: list[NeighbourLists], record_ids: Sequence[str], fanout: int
) -> None:
    requests = [[record_id for record_id in dict.fromkeys(record_ids) if record_id not in lists] for lists in memo]
    asked = [index for index, wanted in enumerate(requests) if wanted]
    results = await asyncio.gather(
        *(sources[index].neighbours(requests[index], fanout) for index in asked), return_exceptions=True
    )
    fetched: list[dict[str, list[tuple[str, float]]]] = []
    for result in results:
        if isinstance(result, BaseException):
            raise result
        fetched.append(result)
    for index, lists in zip(asked, fetched, strict=True):
        for record_id in requests[index]:
            memo[index][record_id] = _cleaned(record_id, lists.get(record_id, []), fanout)


def _cleaned(record_id: str, neighbours: Sequence[tuple[str, float]], fanout: int) -> list[tuple[str, float]]:
    best: dict[str, float] = {}
    for neighbour, weight in neighbours:
        if neighbour != record_id and math.isfinite(weight):
            best[neighbour] = max(best.get(neighbour, weight), weight)
    return sorted(best.items(), key=lambda item: (-item[1], item[0]))[:fanout]


def _expansion(memo: list[NeighbourLists], record_id: str, min_weight: float) -> list[str]:
    candidates: dict[str, float] = {}
    for lists in memo:
        for neighbour, weight in lists.get(record_id, []):
            if weight >= min_weight:
                candidates[neighbour] = max(candidates.get(neighbour, weight), weight)
    return [neighbour for neighbour, _weight in sorted(candidates.items(), key=lambda item: (-item[1], item[0]))]


def _connected(seed_record_id: str, edges: Sequence[GraphEdge]) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set()).add(edge.source)
    reached = {seed_record_id}
    pending = [seed_record_id]
    while pending:
        for neighbour in adjacency.get(pending.pop(), ()):
            if neighbour not in reached:
                reached.add(neighbour)
                pending.append(neighbour)
    return reached


def _degrees(edges: Sequence[GraphEdge]) -> dict[str, int]:
    neighbours: dict[str, set[str]] = {}
    for edge in edges:
        neighbours.setdefault(edge.source, set()).add(edge.target)
        neighbours.setdefault(edge.target, set()).add(edge.source)
    return {record_id: len(adjacent) for record_id, adjacent in neighbours.items()}
