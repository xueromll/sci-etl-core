import pandas as pd

from sci_etl_core.processors.normalization import DefaultKeyNormalizer, NormalizationStep


def test_default_key_normalizer_strips_and_lowercases():
    normalizer = DefaultKeyNormalizer()
    assert normalizer.normalize(" Test-Name_1 ") == "testname1"


def test_default_key_normalizer_handles_missing_values():
    normalizer = DefaultKeyNormalizer()
    assert normalizer.normalize(None) == ""
    assert normalizer.normalize(float("nan")) == ""


def test_normalization_step_adds_column():
    frame = pd.DataFrame({"name": ["Foo Bar", "baz-qux"]})
    step = NormalizationStep(key_column="name", normalizer=DefaultKeyNormalizer())
    result = step.process(frame)
    assert result["_norm_key"].tolist() == ["foobar", "bazqux"]
