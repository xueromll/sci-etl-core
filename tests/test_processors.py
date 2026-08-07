from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sci_etl_core.processors.base import Processor, ProcessorChain
from sci_etl_core.processors.clustering import ClusteringStep, FeatureExtractor
from sci_etl_core.processors.dedup import DeduplicationStep, NeighborMatcher
from sci_etl_core.processors.normalization import DefaultKeyNormalizer, NormalizationStep
from sci_etl_core.processors.quality import CompletenessStep, QualityFlagStep


class TestDefaultKeyNormalizer:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (" Test-Name_1 ", "testname1"),
            ("ALPHA", "alpha"),
            ("a b c", "abc"),
            ("NGC 1052-DF2", "ngc1052df2"),
            ("", ""),
        ],
    )
    def test_normalizes_to_lowercase_alnum(self, raw, expected):
        assert DefaultKeyNormalizer().normalize(raw) == expected

    @pytest.mark.parametrize("missing", [None, float("nan")])
    def test_missing_values_become_empty_string(self, missing):
        assert DefaultKeyNormalizer().normalize(missing) == ""


class TestNormalizationStep:
    def test_adds_normalized_key_column(self):
        frame = pd.DataFrame({"name": ["Foo Bar", "baz-qux"]})
        result = NormalizationStep("name", DefaultKeyNormalizer()).process(frame)
        assert result["_norm_key"].tolist() == ["foobar", "bazqux"]

    def test_does_not_mutate_input_frame(self):
        frame = pd.DataFrame({"name": ["X"]})
        NormalizationStep("name", DefaultKeyNormalizer()).process(frame)
        assert "_norm_key" not in frame.columns

    def test_custom_output_column(self):
        frame = pd.DataFrame({"name": ["X"]})
        result = NormalizationStep("name", DefaultKeyNormalizer(), output_column="key").process(frame)
        assert "key" in result.columns


class TestDeduplicationStep:
    def _normalized(self) -> pd.DataFrame:
        frame = pd.DataFrame({"name": ["Alpha", "alpha", "Beta"], "value": [1.0, None, 3.0]})
        return NormalizationStep("name", DefaultKeyNormalizer()).process(frame)

    def test_collapses_rows_sharing_a_normalized_key(self):
        result = DeduplicationStep("_norm_key").process(self._normalized())
        assert len(result) == 2
        assert set(result["_norm_key"]) == {"alpha", "beta"}

    def test_returns_empty_frame_unchanged(self):
        empty = pd.DataFrame({"_norm_key": []})
        assert DeduplicationStep("_norm_key").process(empty).empty

    def test_matcher_merges_missing_fields_from_dropped_row(self):
        class AlwaysMatchFirstTwo(NeighborMatcher):
            def find_matches(self, frame, threshold):
                return [(0, 1)] if len(frame) > 1 else []

        frame = pd.DataFrame({"_norm_key": ["a", "b"], "value": [None, 42.0]})
        result = DeduplicationStep("_norm_key", matcher=AlwaysMatchFirstTwo()).process(frame)
        assert len(result) == 1
        assert result.iloc[0]["value"] == 42.0

    def test_matcher_is_not_called_when_none(self, mocker):
        matcher = mocker.Mock(spec=NeighborMatcher)
        step = DeduplicationStep("_norm_key", matcher=None)
        step.process(self._normalized())
        matcher.find_matches.assert_not_called()


class TestClusteringStep:
    class _PassthroughFeatures(FeatureExtractor):
        def __init__(self, columns):
            self._columns = columns

        def extract(self, frame):
            valid = frame.dropna(subset=self._columns)
            return valid[self._columns].to_numpy(dtype=float), valid.index

    def test_assigns_cluster_labels_to_dense_points(self):
        frame = pd.DataFrame({"x": [0.0, 0.1, 10.0, 10.1], "y": [0.0, 0.1, 10.0, 10.1]})
        step = ClusteringStep(self._PassthroughFeatures(["x", "y"]), eps=1.0, min_samples=2)
        result = step.process(frame)
        assert result.loc[0, "cluster_id"] == result.loc[1, "cluster_id"]
        assert result.loc[2, "cluster_id"] == result.loc[3, "cluster_id"]
        assert result.loc[0, "cluster_id"] != result.loc[2, "cluster_id"]

    def test_defaults_to_noise_when_too_few_points(self):
        frame = pd.DataFrame({"x": [0.0], "y": [0.0]})
        result = ClusteringStep(self._PassthroughFeatures(["x", "y"]), min_samples=2).process(frame)
        assert result["cluster_id"].tolist() == [-1]

    def test_rows_with_missing_features_stay_noise(self):
        frame = pd.DataFrame({"x": [0.0, 0.1, np.nan], "y": [0.0, 0.1, 5.0]})
        result = ClusteringStep(self._PassthroughFeatures(["x", "y"]), eps=1.0, min_samples=2).process(frame)
        assert result.loc[2, "cluster_id"] == -1


class TestCompletenessStep:
    def test_computes_percentage_of_filled_tracked_fields(self):
        frame = pd.DataFrame({"a": [1.0, None], "b": [2.0, 2.0], "c": [None, None]})
        result = CompletenessStep(["a", "b", "c"]).process(frame)
        assert result.loc[0, "completeness_pct"] == pytest.approx(66.7)
        assert result.loc[1, "completeness_pct"] == pytest.approx(33.3)

    def test_zero_when_no_tracked_fields_exist(self):
        frame = pd.DataFrame({"other": [1.0]})
        result = CompletenessStep(["missing"]).process(frame)
        assert result["completeness_pct"].tolist() == [0.0]


class TestQualityFlagStep:
    @pytest.mark.parametrize(
        "pct, flag",
        [(100.0, "Confirmed"), (75.0, "Needs Review"), (50.0, "Needs Review"), (10.0, "Low Confidence")],
    )
    def test_classifies_by_completeness(self, pct, flag):
        frame = pd.DataFrame({"completeness_pct": [pct]})
        result = QualityFlagStep(review_threshold=50.0).process(frame)
        assert result.loc[0, "quality_flag"] == flag

    def test_nan_completeness_is_low_confidence(self):
        frame = pd.DataFrame({"completeness_pct": [np.nan]})
        result = QualityFlagStep().process(frame)
        assert result.loc[0, "quality_flag"] == "Low Confidence"


class TestProcessorChain:
    def test_applies_steps_in_order(self):
        frame = pd.DataFrame({"name": ["Alpha", "alpha"], "a": [1.0, None]})
        chain = ProcessorChain(
            [
                NormalizationStep("name", DefaultKeyNormalizer()),
                DeduplicationStep("_norm_key"),
                CompletenessStep(["a"]),
                QualityFlagStep(),
            ]
        )
        result = chain.process(frame)
        assert len(result) == 1
        assert "quality_flag" in result.columns

    def test_empty_chain_is_identity(self):
        frame = pd.DataFrame({"x": [1]})
        pd.testing.assert_frame_equal(ProcessorChain([]).process(frame), frame)

    def test_chain_invokes_each_step_once(self, mocker):
        step_a = mocker.Mock(spec=Processor)
        step_a.process.side_effect = lambda f: f
        step_b = mocker.Mock(spec=Processor)
        step_b.process.side_effect = lambda f: f
        frame = pd.DataFrame({"x": [1]})
        ProcessorChain([step_a, step_b]).process(frame)
        step_a.process.assert_called_once()
        step_b.process.assert_called_once()
