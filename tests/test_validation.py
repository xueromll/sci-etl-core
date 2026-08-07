from __future__ import annotations

import pytest

from sci_etl_core.processors.validation import (
    CompositeValidator,
    KeywordExclusionValidator,
    NumericRangeValidator,
    RecordValidator,
)


@pytest.fixture
def keyword_validator() -> KeywordExclusionValidator:
    return KeywordExclusionValidator(key_field="name", forbidden_keywords=["mock", "simulation"])


class TestKeywordExclusionValidator:
    @pytest.mark.parametrize(
        "name",
        [
            "Real Object",
            "mocktail",
            "premock",
            "dissimulation",
            "NGC 1052-DF2",
            "sim",
            "A galaxy named Foo",
        ],
    )
    def test_accepts_values_without_a_forbidden_token(self, keyword_validator, name):
        assert keyword_validator.is_valid({"name": name}) is True

    @pytest.mark.parametrize(
        "name",
        [
            "mock_object_1",
            "MOCK galaxy",
            "simulation run",
            "a mock in the middle",
            "simulation_v2",
            "mock-1",
            "mock1",
            "mock@object",
            "mock+source",
            "Simulation",
        ],
    )
    def test_rejects_any_value_containing_a_forbidden_token(self, keyword_validator, name):
        assert keyword_validator.is_valid({"name": name}) is False

    @pytest.mark.parametrize("name", ["", "   ", "null", "None", "UNKNOWN", "n/a", "nan"])
    def test_rejects_null_like_and_empty_values(self, keyword_validator, name):
        assert keyword_validator.is_valid({"name": name}) is False

    def test_rejects_when_key_field_is_absent(self, keyword_validator):
        assert keyword_validator.is_valid({"other": "value"}) is False

    def test_matching_is_case_insensitive_for_keywords_and_values(self):
        validator = KeywordExclusionValidator(key_field="name", forbidden_keywords=["MoCk"])
        assert validator.is_valid({"name": "a MOCK here"}) is False
        assert validator.is_valid({"name": "genuine"}) is True

    def test_multi_token_keyword_matches_only_as_a_contiguous_phrase(self):
        validator = KeywordExclusionValidator(key_field="name", forbidden_keywords=["fake-source"])
        assert validator.is_valid({"name": "fake source detection"}) is False
        assert validator.is_valid({"name": "a FAKE_SOURCE here"}) is False
        assert validator.is_valid({"name": "a source of light"}) is True
        assert validator.is_valid({"name": "source fake"}) is True
        assert validator.is_valid({"name": "genuine object"}) is True

    def test_catalog_designation_does_not_block_its_whole_catalog(self):
        validator = KeywordExclusionValidator(key_field="name", forbidden_keywords=["NGC 1234"])
        assert validator.is_valid({"name": "NGC 1234"}) is False
        assert validator.is_valid({"name": "ngc1234"}) is False
        assert validator.is_valid({"name": "NGC 5678"}) is True
        assert validator.is_valid({"name": "NGC 12345"}) is True
        assert validator.is_valid({"name": "NGC 1052-DF2"}) is True

    def test_non_latin_keywords_are_matched(self):
        validator = KeywordExclusionValidator(key_field="name", forbidden_keywords=["Макет"])
        assert validator.is_valid({"name": "макет галактики"}) is False
        assert validator.is_valid({"name": "галактика Андромеды"}) is True

    def test_non_string_key_value_is_coerced_before_matching(self):
        validator = KeywordExclusionValidator(key_field="name", forbidden_keywords=["123"])
        assert validator.is_valid({"name": 123}) is False
        assert validator.is_valid({"name": 456}) is True

    def test_empty_forbidden_list_accepts_all_non_null_values(self):
        validator = KeywordExclusionValidator(key_field="name", forbidden_keywords=[])
        assert validator.is_valid({"name": "anything"}) is True
        assert validator.is_valid({"name": ""}) is False


class TestNumericRangeValidator:
    @pytest.fixture
    def range_validator(self) -> NumericRangeValidator:
        return NumericRangeValidator({"ra": (0.0, 360.0), "dec": (-90.0, 90.0)})

    @pytest.mark.parametrize(
        "record",
        [
            {"ra": 0.0, "dec": 0.0},
            {"ra": 360.0, "dec": 90.0},
            {"ra": 180.0, "dec": -90.0},
            {"ra": "45.5", "dec": "12.0"},
        ],
    )
    def test_accepts_values_inside_inclusive_bounds(self, range_validator, record):
        assert range_validator.is_valid(record) is True

    @pytest.mark.parametrize(
        "record",
        [
            {"ra": -0.1, "dec": 0.0},
            {"ra": 360.1, "dec": 0.0},
            {"ra": 10.0, "dec": 90.1},
            {"ra": 10.0, "dec": -90.1},
        ],
    )
    def test_rejects_values_outside_bounds(self, range_validator, record):
        assert range_validator.is_valid(record) is False

    def test_missing_fields_are_skipped_not_rejected(self, range_validator):
        assert range_validator.is_valid({"ra": 10.0}) is True
        assert range_validator.is_valid({}) is True

    def test_none_value_is_skipped(self, range_validator):
        assert range_validator.is_valid({"ra": None, "dec": 0.0}) is True

    @pytest.mark.parametrize("bad_value", ["not-a-number", "", object()])
    def test_uncoercible_value_is_rejected(self, range_validator, bad_value):
        assert range_validator.is_valid({"ra": bad_value, "dec": 0.0}) is False


class TestCompositeValidator:
    def _keyword(self) -> KeywordExclusionValidator:
        return KeywordExclusionValidator(key_field="name", forbidden_keywords=["mock"])

    def _range(self) -> NumericRangeValidator:
        return NumericRangeValidator({"ra": (0.0, 360.0)})

    def test_passes_only_when_all_children_pass(self):
        composite = CompositeValidator([self._keyword(), self._range()])
        assert composite.is_valid({"name": "Real", "ra": 10.0}) is True

    @pytest.mark.parametrize(
        "record",
        [
            {"name": "mock_1", "ra": 10.0},
            {"name": "Real", "ra": 999.0},
            {"name": "mock", "ra": 999.0},
        ],
    )
    def test_fails_when_any_child_fails(self, record):
        composite = CompositeValidator([self._keyword(), self._range()])
        assert composite.is_valid(record) is False

    def test_empty_composite_accepts_everything(self):
        assert CompositeValidator([]).is_valid({"anything": "goes"}) is True

    def test_short_circuits_on_first_failure(self, mocker):
        first = mocker.Mock(spec=RecordValidator)
        first.is_valid.return_value = False
        second = mocker.Mock(spec=RecordValidator)
        second.is_valid.return_value = True

        assert CompositeValidator([first, second]).is_valid({"x": 1}) is False
        first.is_valid.assert_called_once()
        second.is_valid.assert_not_called()
