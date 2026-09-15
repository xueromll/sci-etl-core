from __future__ import annotations

import dataclasses

import pytest

from sci_etl_core.discovery import DiscoveryResult, Facet
from sci_etl_core.search.fusion import FusedHit
from sci_etl_core.search.graph import DiscoveryGraph, GraphNode
from sci_etl_core.search.parser import parse_query
from sci_etl_core.search.query import describe


def test_a_result_carries_everything_a_view_renders():
    graph = DiscoveryGraph((GraphNode("r1", "Dwarf galaxies"),), (), "r1", True)
    result = DiscoveryResult(
        query_text="dwarf -quasar",
        chips=tuple(describe(parse_query("dwarf -quasar"))),
        hits=(FusedHit("r1", 0.03, lexical_rank=1),),
        graph=graph,
        facets=(Facet("year", (("2025", 3), ("2024", 1))),),
        total_matched=4,
        elapsed_ms=12.5,
        degraded=("semantic",),
    )
    assert [chip.text for chip in result.chips] == ["dwarf", "quasar"]
    assert result.graph.communities_converged is True
    assert (result.degraded, result.skipped) == (("semantic",), ())


def test_the_read_model_is_immutable():
    facet = Facet("year")
    assert facet.counts == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        facet.key = "categories"
