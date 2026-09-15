from __future__ import annotations

import asyncio

import pytest

from sci_etl_core.search.edges import AsyncEdgeSource
from sci_etl_core.search.graph import GraphEdge, GraphParams, build_discovery_graph
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_memory import InMemoryTextSearchStore

TABLE = {
    "s": [("a", 0.9), ("b", 0.8), ("c", 0.3)],
    "a": [("s", 0.9), ("b", 0.7), ("d", 0.6)],
    "b": [("s", 0.8), ("a", 0.7)],
    "c": [("s", 0.3)],
    "d": [("a", 0.6), ("e", 0.5)],
    "e": [("d", 0.5)],
}


class TableSource(AsyncEdgeSource):
    def __init__(self, table, kind="semantic", error=None, delay=0.0):
        self.table = table
        self._kind = kind
        self.error = error
        self.delay = delay
        self.calls = []
        self.finished = False

    @property
    def kind(self):
        return self._kind

    async def neighbours(self, record_ids, limit):
        self.calls.append((list(record_ids), limit))
        await asyncio.sleep(self.delay)
        self.finished = True
        if self.error is not None:
            raise self.error
        return {record_id: self.table.get(record_id, []) for record_id in record_ids}


async def text_store():
    store = InMemoryTextSearchStore(facet_keys=("year",))
    await store.index(
        [
            SearchDocument("s", title="Seed", metadata={"year": "2024"}),
            SearchDocument("a", title="Alpha"),
            SearchDocument("b", title="Beta"),
        ]
    )
    return store


def summary(graph):
    return [(node.record_id, node.degree) for node in graph.nodes], [
        (edge.source, edge.target, edge.weight, edge.kind) for edge in graph.edges
    ]


class TestBuildDiscoveryGraph:
    @pytest.mark.asyncio
    async def test_grows_breadth_first_and_keeps_mutual_edges(self):
        source = TableSource(TABLE)
        graph = await build_discovery_graph("s", [source], await text_store())
        assert summary(graph) == (
            [("s", 2), ("a", 3), ("b", 2), ("d", 1)],
            [
                ("a", "b", 0.7, "semantic"),
                ("a", "d", 0.6, "semantic"),
                ("a", "s", 0.9, "semantic"),
                ("b", "s", 0.8, "semantic"),
            ],
        )
        assert (graph.seed_record_id, graph.communities_converged) == ("s", True)
        assert [node.community for node in graph.nodes] == [0, 0, 0, 0]
        assert [(node.title, node.metadata) for node in graph.nodes] == [
            ("Seed", {"year": "2024"}),
            ("Alpha", {}),
            ("Beta", {}),
            ("", {}),
        ]

    @pytest.mark.asyncio
    async def test_issues_one_batched_call_per_level_and_never_fetches_a_record_twice(self):
        source = TableSource(TABLE)
        await build_discovery_graph("s", [source], await text_store())
        assert source.calls == [(["s"], 8), (["a", "b"], 8), (["d"], 8)]

    @pytest.mark.asyncio
    async def test_without_mutual_only_one_sided_edges_stay_and_no_extra_call_is_made(self):
        source = TableSource({"s": [("x", 0.9)]})
        params = GraphParams(mutual_only=False)
        graph = await build_discovery_graph("s", [source], InMemoryTextSearchStore(), params=params)
        assert summary(graph) == ([("s", 1), ("x", 1)], [("s", "x", 0.9, "semantic")])
        assert source.calls == [(["s"], 8), (["x"], 8)]

    @pytest.mark.asyncio
    async def test_records_left_unconnected_by_mutual_pruning_are_dropped(self):
        source = TableSource({"s": [("x", 0.9)]})
        graph = await build_discovery_graph("s", [source], InMemoryTextSearchStore())
        assert summary(graph) == ([("s", 0)], [])

    @pytest.mark.parametrize(
        "max_nodes, nodes, calls",
        [
            (3, ["s", "a", "b"], [(["s"], 8), (["a", "b"], 8)]),
            (2, ["s", "a"], [(["s"], 8), (["a"], 8)]),
            (1, ["s"], [(["s"], 8)]),
        ],
    )
    @pytest.mark.asyncio
    async def test_max_nodes_is_enforced_before_each_level_and_while_it_grows(self, max_nodes, nodes, calls):
        source = TableSource(TABLE)
        params = GraphParams(max_nodes=max_nodes)
        graph = await build_discovery_graph("s", [source], await text_store(), params=params)
        assert [node.record_id for node in graph.nodes] == nodes
        assert source.calls == calls

    @pytest.mark.asyncio
    async def test_growth_stops_when_a_level_adds_no_record(self):
        source = TableSource(TABLE)
        graph = await build_discovery_graph("c", [source], InMemoryTextSearchStore(), params=GraphParams(depth=3))
        assert summary(graph) == ([("c", 0)], [])
        assert source.calls == [(["c"], 8)]

    @pytest.mark.asyncio
    async def test_neighbour_lists_are_cleaned_before_use(self):
        messy = {"s": [("s", 1.0), ("a", 0.5), ("a", 0.9), ("b", 0.8), ("c", 0.7), ("z", float("nan"))]}
        params = GraphParams(depth=1, fanout=2, min_weight=0.0, mutual_only=False)
        graph = await build_discovery_graph("s", [TableSource(messy)], InMemoryTextSearchStore(), params=params)
        assert summary(graph)[1] == [("a", "s", 0.9, "semantic"), ("b", "s", 0.8, "semantic")]

    @pytest.mark.asyncio
    async def test_sources_run_concurrently_and_keep_their_edge_kinds(self):
        first_started, second_started = asyncio.Event(), asyncio.Event()

        class Gated(TableSource):
            def __init__(self, table, kind, started, other):
                super().__init__(table, kind)
                self.started, self.other = started, other

            async def neighbours(self, record_ids, limit):
                self.started.set()
                await asyncio.wait_for(self.other.wait(), 2)
                return await super().neighbours(record_ids, limit)

        semantic = Gated({"s": [("a", 0.9)], "a": [("s", 0.9)]}, "semantic", first_started, second_started)
        metadata = Gated({"s": [("a", 0.5)], "a": [("s", 0.5)]}, "metadata", second_started, first_started)
        graph = await build_discovery_graph("s", [semantic, metadata], InMemoryTextSearchStore())
        assert summary(graph)[1] == [("a", "s", 0.5, "metadata"), ("a", "s", 0.9, "semantic")]

    @pytest.mark.asyncio
    async def test_the_first_failing_source_in_order_is_raised_after_every_source_finished(self):
        slow_failure = TableSource(TABLE, error=RuntimeError("first"), delay=0.02)
        fast_failure = TableSource(TABLE, error=RuntimeError("second"))
        slow_success = TableSource(TABLE, delay=0.04)
        with pytest.raises(RuntimeError, match="^first$"):
            await build_discovery_graph("s", [slow_failure, fast_failure, slow_success], InMemoryTextSearchStore())
        assert slow_success.finished

    @pytest.mark.asyncio
    async def test_unconverged_communities_are_reported(self):
        source = TableSource({"s": [("a", 0.9)], "a": [("s", 0.9)]})
        params = GraphParams(max_iterations=1)
        graph = await build_discovery_graph("s", [source], InMemoryTextSearchStore(), params=params)
        assert graph.communities_converged is False
        assert graph.edges == (GraphEdge("a", "s", 0.9, "semantic"),)

    @pytest.mark.asyncio
    async def test_at_least_one_source_is_required(self):
        with pytest.raises(ValueError, match="needs at least one edge source"):
            await build_discovery_graph("s", [], InMemoryTextSearchStore())
