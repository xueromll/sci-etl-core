from __future__ import annotations

import numpy as np
import pytest

from sci_etl_core.embeddings._similarity import (
    l2_normalize,
    to_matrix,
    top_similarity,
    unit_vector,
)


class TestToMatrix:
    def test_empty_input_yields_empty_matrix(self):
        matrix = to_matrix([])
        assert matrix.shape == (0, 0)

    def test_stacks_rows_as_float(self):
        matrix = to_matrix([[1, 2], [3, 4]])
        assert matrix.dtype == np.float64
        assert matrix.tolist() == [[1.0, 2.0], [3.0, 4.0]]


class TestL2Normalize:
    def test_empty_matrix_is_returned_unchanged(self):
        empty = np.empty((0, 0), dtype=np.float64)
        assert l2_normalize(empty).size == 0

    def test_rows_scaled_to_unit_length_and_zero_rows_survive(self):
        normalized = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
        assert normalized[0].tolist() == pytest.approx([0.6, 0.8])
        assert normalized[1].tolist() == [0.0, 0.0]

    @pytest.mark.parametrize(
        "row",
        [
            [1.1514339432346129e-161],
            [3e-200, 4e-200, 0.0],
            [5e-324, 1e-323],
            [1e200, 1e200],
        ],
        ids=["tiny", "tiny-with-zero", "subnormal", "overflowing-square"],
    )
    def test_rows_at_extreme_magnitudes_reach_unit_length(self, row):
        # A plain norm squares first: tiny components round in the subnormal
        # range and huge ones overflow, so none of these came out unit length.
        normalized = l2_normalize(to_matrix([row]))
        assert np.linalg.norm(normalized[0]) == pytest.approx(1.0, abs=1e-12)

    def test_non_finite_rows_are_passed_through(self):
        matrix = np.array([[np.inf, 1.0], [np.nan, 1.0]])
        normalized = l2_normalize(matrix)
        assert normalized[0].tolist() == [np.inf, 1.0]
        assert np.isnan(normalized[1][0]) and normalized[1][1] == 1.0


class TestUnitVector:
    def test_empty_vector_is_returned_unchanged(self):
        assert unit_vector([]).size == 0

    def test_zero_vector_is_left_untouched(self):
        assert unit_vector([0.0, 0.0]).tolist() == [0.0, 0.0]

    def test_scales_to_unit_length(self):
        assert unit_vector([3.0, 4.0]).tolist() == pytest.approx([0.6, 0.8])


class TestTopSimilarity:
    def test_empty_references_score_lowest(self):
        assert top_similarity([1.0, 0.0], np.empty((0, 0))) == -1.0

    def test_empty_query_scores_lowest(self):
        assert top_similarity([], np.array([[1.0, 0.0]])) == -1.0

    def test_zero_norm_query_scores_lowest(self):
        assert top_similarity([0.0, 0.0], np.array([[1.0, 0.0]])) == -1.0

    @pytest.mark.parametrize(
        "query", [[1.1514339432346129e-161], [5e-324, 1e-323]], ids=["tiny", "subnormal"]
    )
    def test_tiny_query_matching_a_reference_scores_one(self, query):
        references = l2_normalize(to_matrix([query]))
        assert top_similarity(query, references) == pytest.approx(1.0, abs=1e-12)

    def test_returns_nearest_reference_similarity(self):
        references = l2_normalize(np.array([[1.0, 0.0], [0.0, 1.0]]))
        # The query leans toward the first reference; cosine equals the query's
        # normalized x-component, which beats its similarity to the second.
        expected = 0.9 / (0.9**2 + 0.1**2) ** 0.5
        assert top_similarity([0.9, 0.1], references) == pytest.approx(expected)
