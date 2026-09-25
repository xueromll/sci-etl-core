from __future__ import annotations

import random

import pytest

from sci_etl_core.search.filters import MetadataFilter
from sci_etl_core.search.graph import (
    DiscoveryGraph,
    GraphEdge,
    GraphNode,
    GraphParams,
    filter_graph,
    label_communities,
    select_edges,
)


def edge(source, target, weight=1.0, kind="semantic"):
    return GraphEdge(source, target, weight, kind)


class TestGraphParams:
    def test_defaults(self):
        assert GraphParams() == GraphParams(
            depth=2, fanout=8, min_weight=0.35, max_nodes=200, mutual_only=True, max_iterations=20
        )

    @pytest.mark.parametrize(
        ("options", "message"),
        [
            ({"depth": -1}, "depth must not be negative"),
            ({"fanout": 0}, "fanout must be at least 1"),
            ({"max_nodes": 0}, "max_nodes must be at least 1"),
            ({"max_iterations": 0}, "max_iterations must be at least 1"),
            ({"min_weight": float("nan")}, "min_weight must be finite"),
        ],
    )
    def test_impossible_values_are_rejected(self, options, message):
        with pytest.raises(ValueError, match=message):
            GraphParams(**options)


LISTS = {
    "a": [("b", 0.9), ("c", 0.8), ("a", 1.0), ("outside", 0.9)],
    "b": [("a", 0.6)],
    "c": [("d", 0.7), ("e", 0.1)],
    "outside": [("a", 0.9)],
}


class TestSelectEdges:
    def test_mutual_only_keeps_edges_whose_endpoints_list_each_other(self):
        edges = select_edges([("semantic", LISTS)], ["a", "b", "c", "d", "e"], min_weight=0.35, mutual_only=True)
        assert edges == [edge("a", "b", 0.9)]

    def test_without_mutual_only_one_sided_edges_are_kept(self):
        edges = select_edges([("semantic", LISTS)], ["a", "b", "c", "d", "e"], min_weight=0.35, mutual_only=False)
        assert edges == [edge("a", "b", 0.9), edge("a", "c", 0.8), edge("c", "d", 0.7)]

    def test_self_loops_light_edges_and_records_outside_the_nodes_are_dropped(self):
        edges = select_edges([("semantic", LISTS)], ["a", "c", "e"], min_weight=0.0, mutual_only=False)
        assert edges == [edge("a", "c", 0.8), edge("c", "e", 0.1)]

    def test_each_source_keeps_its_own_kind(self):
        sources = [("semantic", {"a": [("b", 0.5)]}), ("metadata", {"b": [("a", 0.4)]})]
        edges = select_edges(sources, ["a", "b"], min_weight=0.0, mutual_only=False)
        assert edges == [edge("a", "b", 0.4, "metadata"), edge("a", "b", 0.5, "semantic")]


def k2_3():
    return ["a", "b", "c", "d", "e"], [edge(left, right) for left in ("a", "b") for right in ("c", "d", "e")]


class TestLabelCommunities:
    @pytest.mark.parametrize("graph", [(["a", "b"], [edge("a", "b")]), k2_3()])
    def test_graphs_that_oscillate_under_synchronous_update_converge_to_one_community(self, graph):
        nodes, edges = graph
        expected = ({node: 0 for node in nodes}, True)
        generator = random.Random(7)
        for _run in range(10):
            shuffled_nodes, shuffled_edges = nodes[:], edges[:]
            generator.shuffle(shuffled_nodes)
            generator.shuffle(shuffled_edges)
            assert label_communities(shuffled_nodes, shuffled_edges) == expected

    def test_k2_uses_its_whole_budget_on_its_one_changing_pass(self):
        assert label_communities(["a", "b"], [edge("a", "b")], max_iterations=1) == ({"a": 0, "b": 0}, False)

    @pytest.mark.parametrize(("max_iterations", "converged"), [(2, False), (3, True)])
    def test_a_graph_needing_two_changing_passes_converges_on_the_third(self, max_iterations, converged):
        edges = [edge("a", "c"), edge("a", "e"), edge("c", "e"), edge("d", "e")]
        _, result = label_communities(["a", "c", "d", "e"], edges, max_iterations=max_iterations)
        assert result is converged

    def test_two_triangles_joined_by_a_light_edge_are_two_communities(self):
        edges = [
            edge("a", "b"),
            edge("b", "c"),
            edge("a", "c"),
            edge("d", "e"),
            edge("e", "f"),
            edge("d", "f"),
            edge("c", "d", 0.1),
        ]
        assert label_communities(list("fedcba"), edges) == ({"a": 0, "b": 0, "c": 0, "d": 1, "e": 1, "f": 1}, True)

    def test_an_isolated_node_keeps_its_own_community(self):
        assert label_communities(["a", "b", "z"], [edge("a", "b")]) == ({"a": 0, "b": 0, "z": 1}, True)

    def test_parallel_edges_count_once_with_the_heaviest_weight(self):
        triangles = [edge("a", "b"), edge("b", "c"), edge("a", "c"), edge("d", "e"), edge("e", "f"), edge("d", "f")]
        bridges = [edge("c", "d", 0.9, kind) for kind in ("semantic", "metadata", "citation")]
        communities, _ = label_communities(list("abcdef"), [*triangles, *bridges])
        assert communities == {"a": 0, "b": 0, "c": 0, "d": 1, "e": 1, "f": 1}

    def test_self_loops_and_edges_to_unknown_records_are_ignored(self):
        assert label_communities(["a", "b"], [edge("a", "a"), edge("a", "zz")]) == ({"a": 0, "b": 1}, True)

    def test_a_pass_budget_below_one_is_rejected(self):
        with pytest.raises(ValueError, match="max_iterations must be at least 1"):
            label_communities(["a"], [], max_iterations=0)


GRAPH = DiscoveryGraph(
    nodes=(
        GraphNode("s", "Seed", 2, 0, {"year": "2024"}),
        GraphNode("a", "A", 2, 0, {"year": "2025"}),
        GraphNode("b", "B", 2, 1, {"year": "2024"}),
        GraphNode("c", "C", 2, 1, {"year": "2025"}),
    ),
    edges=(edge("a", "b"), edge("a", "s"), edge("b", "c"), edge("c", "s")),
    seed_record_id="s",
    communities_converged=False,
)


def summary(graph):
    return [(node.record_id, node.degree) for node in graph.nodes], [(e.source, e.target) for e in graph.edges]


class TestFilterGraph:
    def test_matched_ids_keep_their_nodes_and_the_seed(self):
        filtered = filter_graph(GRAPH, matched_ids={"a", "b"})
        assert summary(filtered) == ([("s", 1), ("a", 2), ("b", 1)], [("a", "b"), ("a", "s")])
        assert (filtered.seed_record_id, filtered.communities_converged) == ("s", False)
        assert [node.community for node in filtered.nodes] == [0, 0, 1]

    def test_metadata_filters_apply_in_memory(self):
        filtered = filter_graph(GRAPH, filters=[MetadataFilter("year", {"2025"})])
        assert summary(filtered) == ([("s", 2), ("a", 1), ("c", 1)], [("a", "s"), ("c", "s")])

    def test_matched_ids_and_negated_filters_combine(self):
        filtered = filter_graph(GRAPH, matched_ids=["a", "c"], filters=[MetadataFilter("year", {"2024"}, negated=True)])
        assert summary(filtered) == ([("s", 2), ("a", 1), ("c", 1)], [("a", "s"), ("c", "s")])

    def test_no_criteria_keeps_everything(self):
        assert filter_graph(GRAPH) == GRAPH

    def test_two_filters_on_one_key_are_rejected(self):
        with pytest.raises(ValueError, match="Only one filter per key"):
            filter_graph(GRAPH, filters=[MetadataFilter("year", {"2024"}), MetadataFilter("year", {"2025"})])
