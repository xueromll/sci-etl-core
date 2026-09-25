from __future__ import annotations

import itertools

import pytest

from sci_etl_core.search.fusion import FusedHit, FusionParams, normalized_score_fusion, reciprocal_rank_fusion


def ranked(*record_ids):
    return [(record_id, 0.0) for record_id in record_ids]


class TestReciprocalRankFusion:
    def test_a_record_scores_the_sum_of_one_over_k_plus_its_ranks(self):
        assert reciprocal_rank_fusion([ranked("a", "b"), ranked("b", "c")]) == [
            ("b", pytest.approx(1 / 62 + 1 / 61)),
            ("a", pytest.approx(1 / 61)),
            ("c", pytest.approx(1 / 62)),
        ]

    def test_only_the_order_of_a_list_is_read(self):
        assert reciprocal_rank_fusion([[("a", 0.1), ("b", 99.0)]]) == reciprocal_rank_fusion([ranked("a", "b")])

    def test_equal_fused_scores_are_ordered_by_record_id(self):
        assert [record_id for record_id, _ in reciprocal_rank_fusion([ranked("b", "d"), ranked("c", "a")])] == [
            "b",
            "c",
            "a",
            "d",
        ]

    def test_the_order_of_the_lists_never_changes_the_result(self):
        lists = [ranked("a", "b", "c"), ranked("c", "a"), ranked("d", "b", "a"), ranked("b")]
        expected = reciprocal_rank_fusion(lists)
        for permutation in itertools.permutations(lists):
            assert reciprocal_rank_fusion(list(permutation)) == expected

    def test_a_repeated_record_counts_once_at_its_first_position(self):
        assert reciprocal_rank_fusion([ranked("a", "a", "b")]) == [
            ("a", pytest.approx(1 / 61)),
            ("b", pytest.approx(1 / 62)),
        ]

    @pytest.mark.parametrize("lists", [[], [[]], [[], []]])
    def test_no_records_fuse_to_nothing(self, lists):
        assert reciprocal_rank_fusion(lists) == []

    def test_weights_scale_each_lists_contribution(self):
        fused = reciprocal_rank_fusion([ranked("b"), ranked("a")], FusionParams(weights=(2.0, 0.0)))
        assert fused == [("b", pytest.approx(2 / 61)), ("a", 0.0)]

    def test_k_damps_the_ranks(self):
        fused = reciprocal_rank_fusion([ranked("a", "b")], FusionParams(k=1))
        assert fused == [("a", 0.5), ("b", pytest.approx(1 / 3))]

    def test_weights_must_match_the_lists(self):
        with pytest.raises(ValueError, match="Expected 2 fusion weights, one per ranked list, not 1"):
            reciprocal_rank_fusion([ranked("a"), ranked("b")], FusionParams(weights=(1.0,)))


class TestNormalizedScoreFusion:
    def test_each_list_is_min_max_normalized_then_added(self):
        fused = normalized_score_fusion([[("a", 10.0), ("b", 5.0), ("c", 0.0)], [("c", 0.9), ("a", 0.1)]])
        assert fused == [("a", 1.0), ("c", 1.0), ("b", 0.5)]

    def test_a_list_whose_scores_are_equal_gives_every_record_one(self):
        assert normalized_score_fusion([[("b", 3.0), ("a", 3.0)]]) == [("a", 1.0), ("b", 1.0)]

    def test_a_repeated_record_keeps_its_first_score(self):
        assert normalized_score_fusion([[("a", 1.0), ("b", 0.0), ("a", 5.0)]]) == [("a", 1.0), ("b", 0.0)]

    def test_weights_apply_and_an_empty_list_contributes_nothing(self):
        fused = normalized_score_fusion([[], [("a", 4.0), ("b", 2.0)]], FusionParams(weights=(0.5, 3.0)))
        assert fused == [("a", 3.0), ("b", 0.0)]

    @pytest.mark.parametrize("score", [float("nan"), float("inf")])
    def test_a_score_that_is_not_finite_is_rejected(self, score):
        with pytest.raises(ValueError, match="The score of 'a' is not finite"):
            normalized_score_fusion([[("a", score)]])

    def test_weights_must_match_the_lists(self):
        with pytest.raises(ValueError, match="Expected 1 fusion weights"):
            normalized_score_fusion([ranked("a")], FusionParams(weights=(1.0, 1.0)))


class TestFusionParams:
    def test_defaults(self):
        assert (FusionParams().k, FusionParams().weights) == (60, None)

    def test_weights_given_as_a_list_are_stored_as_a_tuple(self):
        params = FusionParams(weights=[1.0, 0.5])
        assert params.weights == (1.0, 0.5)
        assert hash(params) == hash(FusionParams(weights=(1.0, 0.5)))

    @pytest.mark.parametrize("k", [0, -5])
    def test_k_below_one_is_rejected(self, k):
        with pytest.raises(ValueError, match="k must be at least 1"):
            FusionParams(k=k)

    @pytest.mark.parametrize("weight", [-0.1, float("nan"), float("inf")])
    def test_a_negative_or_non_finite_weight_is_rejected(self, weight):
        with pytest.raises(ValueError, match="Fusion weights must be finite and not negative"):
            FusionParams(weights=(1.0, weight))


def test_a_fused_hit_defaults_to_no_ranks_snippet_or_metadata():
    first, second = FusedHit("r1", 0.5), FusedHit("r2", 0.4)
    assert (first.lexical_rank, first.semantic_rank, first.snippet, first.highlights, first.title) == (
        None,
        None,
        "",
        (),
        "",
    )
    assert first.metadata == {}
    assert first.metadata is not second.metadata
