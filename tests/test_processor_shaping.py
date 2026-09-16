from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sci_etl_core.processors import TableLayoutStep, ValueClipStep


class TestValueClipStep:
    def test_clamps_values_into_the_bounds(self):
        frame = pd.DataFrame({"fraction": [-0.5, 0.25, 1.5]})
        result = ValueClipStep({"fraction": (0.0, 1.0)}).process(frame)
        assert result["fraction"].tolist() == [0.0, 0.25, 1.0]

    def test_non_numeric_values_become_nan(self):
        frame = pd.DataFrame({"fraction": ["0.5", "n/a", None]})
        result = ValueClipStep({"fraction": (0.0, 1.0)}).process(frame)
        assert result.loc[0, "fraction"] == 0.5
        assert result["fraction"].iloc[1:].isna().all()

    def test_missing_columns_are_skipped(self):
        frame = pd.DataFrame({"other": [5]})
        result = ValueClipStep({"fraction": (0.0, 1.0)}).process(frame)
        pd.testing.assert_frame_equal(result, frame)

    def test_does_not_mutate_input_frame(self):
        frame = pd.DataFrame({"fraction": [2.0]})
        ValueClipStep({"fraction": (0.0, 1.0)}).process(frame)
        assert frame.loc[0, "fraction"] == 2.0

    def test_rejects_inverted_bounds(self):
        with pytest.raises(ValueError, match="exceeds its upper bound"):
            ValueClipStep({"fraction": (1.0, 0.0)})

    @pytest.mark.parametrize("bounds", [(float("nan"), 1.0), (0.0, float("nan"))])
    def test_rejects_nan_bounds(self, bounds):
        with pytest.raises(ValueError, match="must not be NaN"):
            ValueClipStep({"fraction": bounds})

    @given(st.lists(st.floats(allow_nan=False, allow_infinity=False, width=32), max_size=20))
    def test_every_value_lands_inside_the_bounds(self, values):
        frame = pd.DataFrame({"x": pd.Series(values, dtype="float64")})
        result = ValueClipStep({"x": (-1.0, 1.0)}).process(frame)
        assert result["x"].between(-1.0, 1.0).all()


class TestTableLayoutStep:
    def test_sorts_by_columns_in_the_given_directions(self):
        frame = pd.DataFrame({"score": [50, 100, 100], "name": ["c", "b", "a"]})
        result = TableLayoutStep(sort_by=[("score", False), ("name", True)]).process(frame)
        assert result["name"].tolist() == ["a", "b", "c"]

    def test_missing_sort_columns_are_ignored(self):
        frame = pd.DataFrame({"name": ["b", "a"]})
        result = TableLayoutStep(sort_by=[("absent", True), ("name", True)]).process(frame)
        assert result["name"].tolist() == ["a", "b"]

    def test_missing_values_sort_last_in_both_directions(self):
        frame = pd.DataFrame({"score": [np.nan, 1.0, 2.0]})
        ascending = TableLayoutStep(sort_by=[("score", True)]).process(frame)
        descending = TableLayoutStep(sort_by=[("score", False)]).process(frame)
        assert ascending["score"].tolist()[:2] == [1.0, 2.0]
        assert descending["score"].tolist()[:2] == [2.0, 1.0]
        assert pd.isna(ascending["score"].iloc[-1])
        assert pd.isna(descending["score"].iloc[-1])

    def test_ties_keep_input_order(self):
        frame = pd.DataFrame({"group": [1, 1, 1], "order": ["first", "second", "third"]})
        result = TableLayoutStep(sort_by=[("group", True)]).process(frame)
        assert result["order"].tolist() == ["first", "second", "third"]

    def test_ties_keep_input_order_across_several_sort_columns(self):
        frame = pd.DataFrame({"a": [1, 1, 1, 0], "b": [2, 2, 2, 2], "order": ["x", "y", "z", "w"]})
        result = TableLayoutStep(sort_by=[("a", False), ("b", True)]).process(frame)
        assert result["order"].tolist() == ["x", "y", "z", "w"]

    def test_leading_columns_come_first_and_the_rest_keep_their_order(self):
        frame = pd.DataFrame(columns=["c", "b", "key", "a", "flag"])
        result = TableLayoutStep(leading_columns=["key", "absent", "flag"]).process(frame)
        assert list(result.columns) == ["key", "flag", "c", "b", "a"]

    def test_hidden_prefixes_drop_columns(self):
        frame = pd.DataFrame({"_norm_key": ["x"], "tmp_score": [1], "name": ["X"], 0: [1]})
        result = TableLayoutStep(hidden_prefixes=["_", "tmp_"], leading_columns=["_norm_key"]).process(frame)
        assert list(result.columns) == ["name", 0]

    def test_hidden_columns_can_still_drive_the_sort(self):
        frame = pd.DataFrame({"_rank": [2, 1], "name": ["b", "a"]})
        result = TableLayoutStep(sort_by=[("_rank", True)], hidden_prefixes=["_"]).process(frame)
        assert result["name"].tolist() == ["a", "b"]
        assert list(result.columns) == ["name"]

    def test_index_is_kept_unless_reset(self):
        frame = pd.DataFrame({"name": ["b", "a"]})
        kept = TableLayoutStep(sort_by=[("name", True)]).process(frame)
        reset = TableLayoutStep(sort_by=[("name", True)], reset_index=True).process(frame)
        assert kept.index.tolist() == [1, 0]
        assert reset.index.tolist() == [0, 1]

    def test_does_not_mutate_input_frame(self):
        frame = pd.DataFrame({"b": [2, 1], "a": [1, 2]})
        result = TableLayoutStep(sort_by=[("b", True)], leading_columns=["a"]).process(frame)
        result.loc[result.index[0], "a"] = 99
        assert frame["b"].tolist() == [2, 1]
        assert frame["a"].tolist() == [1, 2]
        assert list(frame.columns) == ["b", "a"]

    def test_empty_frame_passes_through(self):
        frame = pd.DataFrame(columns=["name"])
        result = TableLayoutStep(sort_by=[("name", True)], leading_columns=["name"]).process(frame)
        assert list(result.columns) == ["name"]
        assert result.empty

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"sort_by": [("a", True), ("a", False)]}, "sort_by names a column more than once"),
            ({"leading_columns": ["a", "a"]}, "leading_columns names a column more than once"),
            ({"hidden_prefixes": [""]}, "must not contain an empty prefix"),
        ],
    )
    def test_rejects_ambiguous_layouts(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            TableLayoutStep(**kwargs)
