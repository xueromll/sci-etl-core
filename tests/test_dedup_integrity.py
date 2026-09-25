from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sci_etl_core.processors.dedup import DeduplicationStep, NeighborMatcher
from sci_etl_core.processors.normalization import DefaultKeyNormalizer, NormalizationStep


class _Pairs(NeighborMatcher):
    def __init__(self, pairs: list[tuple[int, int]]) -> None:
        self._pairs = pairs

    def find_matches(self, frame, threshold):
        return self._pairs


class TestKeyNormalizerContainers:
    @pytest.mark.parametrize("value", [["a", "b"], ("a",), {"x": 1}, {"a"}, np.array(["a", "b"])])
    def test_values_that_cannot_form_a_key_normalize_to_empty(self, value):
        assert DefaultKeyNormalizer().normalize(value) == ""

    def test_numbers_still_form_keys(self):
        assert DefaultKeyNormalizer().normalize(7) == "7"


class TestDedupKeylessRows:
    def test_rows_without_a_key_pass_through_individually(self):
        frame = pd.DataFrame(
            {"name": ["Alpha", None, "!!!", "alpha", ""], "value": [1.0, 2.0, 3.0, None, 5.0]}
        )
        normalized = NormalizationStep("name", DefaultKeyNormalizer()).process(frame)
        result = DeduplicationStep("_norm_key").process(normalized)
        assert result["_norm_key"].tolist() == ["alpha", "", "", ""]
        assert result["value"].tolist() == [1.0, 2.0, 3.0, 5.0]
        assert next(iter(result.columns)) == "_norm_key"

    def test_missing_key_values_are_kept_not_dropped(self):
        frame = pd.DataFrame({"_norm_key": ["a", None, np.nan], "value": [1.0, 2.0, 3.0]})
        result = DeduplicationStep("_norm_key").process(frame)
        assert result["value"].tolist() == [1.0, 2.0, 3.0]

    def test_keyed_rows_are_ordered_by_key(self):
        frame = pd.DataFrame({"value": [1.0, 2.0, 3.0], "_norm_key": ["b", "a", "b"]})
        result = DeduplicationStep("_norm_key").process(frame)
        assert result["_norm_key"].tolist() == ["a", "b"]
        assert result["value"].tolist() == [2.0, 1.0]


class TestDedupMatchChains:
    def _frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "_norm_key": ["a", "b", "c"],
                "value_a": [1.0, None, None],
                "value_b": [None, 2.0, None],
                "value_c": [None, None, 3.0],
            }
        )

    def test_chained_matches_flow_into_the_surviving_row(self):
        result = DeduplicationStep("_norm_key", matcher=_Pairs([(0, 1), (1, 2)])).process(self._frame())
        assert len(result) == 1
        assert result.loc[0, ["value_a", "value_b", "value_c"]].tolist() == [1.0, 2.0, 3.0]

    def test_pair_pointing_back_at_its_own_survivor_is_ignored(self):
        result = DeduplicationStep("_norm_key", matcher=_Pairs([(0, 1), (1, 0)])).process(self._frame())
        assert result["_norm_key"].tolist() == ["a", "c"]

    def test_mergeable_columns_absent_from_the_frame_are_ignored(self):
        step = DeduplicationStep(
            "_norm_key", matcher=_Pairs([(0, 1)]), mergeable_columns=["value_b", "missing"]
        )
        result = step.process(self._frame())
        assert result.loc[0, "value_b"] == 2.0
