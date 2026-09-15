from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from sci_etl_core.search.filters import (
    MetadataFilter,
    encode_metadata,
    matches_filters,
    sanitize_text,
    split_markers,
    tag_rows,
    validate_facet_keys,
    validate_filters,
)
from sci_etl_core.search.store_base import BM25Weights

SRC = Path(__file__).resolve().parents[1] / "src"


class TestMetadataFilter:
    def test_values_are_stored_as_a_frozenset(self):
        assert MetadataFilter("year", ["2024", "2025"]).values == frozenset({"2024", "2025"})

    def test_empty_values_raise_because_nothing_could_match(self):
        with pytest.raises(ValueError, match="The filter on 'year' needs at least one value"):
            MetadataFilter("year", frozenset())

    def test_a_single_string_is_rejected_instead_of_split_into_characters(self):
        with pytest.raises(TypeError, match="not a single string"):
            MetadataFilter("year", "2024")

    def test_is_frozen_and_hashable(self):
        metadata_filter = MetadataFilter("year", {"2024"}, negated=True)
        assert hash(metadata_filter) == hash(MetadataFilter("year", frozenset({"2024"}), negated=True))
        with pytest.raises(dataclasses.FrozenInstanceError):
            metadata_filter.key = "other"


class TestValidateFilters:
    def test_two_filters_on_one_key_raise(self):
        filters = [MetadataFilter("year", {"2024"}), MetadataFilter("year", {"2025"})]
        with pytest.raises(ValueError, match="Only one filter per key is allowed, and 'year' has two"):
            validate_filters(filters)

    def test_opposite_polarities_still_count_as_two_filters_on_one_key(self):
        filters = [MetadataFilter("year", {"2024"}), MetadataFilter("year", {"2025"}, negated=True)]
        with pytest.raises(ValueError, match="Only one filter per key"):
            validate_filters(filters)

    def test_filters_on_distinct_keys_pass(self):
        filters = [MetadataFilter("year", {"2024"}), MetadataFilter("categories", {"GA"})]
        validate_filters(filters, {"year", "categories"})

    def test_a_key_outside_the_allowed_keys_raises(self):
        message = "'year' is not a facet key of this store; facet keys: authors, categories"
        with pytest.raises(ValueError, match=message):
            validate_filters([MetadataFilter("year", {"2024"})], {"categories", "authors"})

    def test_any_key_is_allowed_when_no_allowed_keys_are_given(self):
        validate_filters([MetadataFilter("anything", {"x"})])

    def test_a_store_without_facet_keys_says_so(self):
        with pytest.raises(ValueError, match="facet keys: none configured"):
            validate_facet_keys(["year"], frozenset())


@pytest.mark.parametrize(
    "metadata, filters, expected",
    [
        ({"categories": ["GA", "CO"]}, [MetadataFilter("categories", {"CO"})], True),
        ({"categories": ["GA"]}, [MetadataFilter("categories", {"CO", "HE"})], False),
        ({"categories": ["GA"]}, [MetadataFilter("categories", {"GA"}, negated=True)], False),
        ({"categories": ["GA"]}, [MetadataFilter("categories", {"CO"}, negated=True)], True),
        ({}, [MetadataFilter("year", {"2024"})], False),
        ({}, [MetadataFilter("year", {"2024"}, negated=True)], True),
        ({"year": 2024}, [MetadataFilter("year", {"2024"})], True),
        ({"year": True}, [MetadataFilter("year", {"True"})], False),
        ({"a": "x", "b": "y"}, [MetadataFilter("a", {"x"}), MetadataFilter("b", {"z"})], False),
        ({"a": "x"}, [], True),
    ],
)
def test_matches_filters(metadata, filters, expected):
    assert matches_filters(metadata, filters) is expected


class TestTagRows:
    def test_duplicate_list_values_give_one_row_each(self):
        assert tag_rows({"authors": ["A", "B", "A"]}, ["authors"]) == (("authors", "A"), ("authors", "B"))

    def test_a_scalar_value_gives_one_row(self):
        assert tag_rows({"year": "2025"}, ["year"]) == (("year", "2025"),)

    def test_an_integer_is_tagged_as_its_text(self):
        expected = (("ids", "1"), ("ids", "3"), ("year", "2025"))
        assert tag_rows({"year": 2025, "ids": (3, 1)}, ["year", "ids"]) == expected

    @pytest.mark.parametrize("value", [True, 1.5, None, {"nested": "x"}, [["nested"]], "", [""], [None, False, 2.0]])
    def test_values_that_are_not_text_or_integers_are_skipped(self, value):
        assert tag_rows({"key": value}, ["key"]) == ()

    def test_rows_are_sorted_by_key_then_value_and_limited_to_the_facet_keys(self):
        metadata = {"b": ["z", "a"], "a": "m", "c": "unused"}
        assert tag_rows(metadata, ["b", "a", "a", "missing"]) == (("a", "m"), ("b", "a"), ("b", "z"))


@pytest.mark.parametrize(
    "raw, plain, spans",
    [
        ("no markers", "no markers", ()),
        ("\x02a\x03 b", "a b", ((0, 1),)),
        ("a \x02b\x03", "a b", ((2, 3),)),
        ("\x02a\x03\x02b\x03", "ab", ((0, 1), (1, 2))),
        ("\x02a\x02b\x03c", "abc", ((0, 2),)),
        ("a\x03b", "ab", ()),
        ("a\x02bc", "abc", ((1, 3),)),
        ("a\x02\x03b", "ab", ()),
        ("a\x02", "a", ()),
        ("", "", ()),
    ],
)
def test_split_markers(raw, plain, spans):
    assert split_markers(raw) == (plain, spans)


class TestEncodeMetadata:
    def test_a_date_is_iso_8601(self):
        assert json.loads(encode_metadata({"d": date(2026, 9, 15)})) == {"d": "2026-09-15"}

    def test_a_datetime_is_iso_8601_with_a_t_and_no_space(self):
        value = json.loads(encode_metadata({"d": datetime(2026, 9, 15, 8, 20, tzinfo=timezone.utc)}))["d"]
        assert value == "2026-09-15T08:20:00+00:00"
        assert "T" in value and " " not in value

    def test_a_time_is_iso_8601(self):
        assert json.loads(encode_metadata({"t": time(8, 20, 9)})) == {"t": "08:20:09"}

    def test_bytes_are_rendered_through_repr(self):
        assert json.loads(encode_metadata({"b": b"abc", "a": bytearray(b"x")})) == {
            "b": "b'abc'",
            "a": "bytearray(b'x')",
        }

    def test_bytes_encode_under_python_bb(self):
        result = subprocess.run(
            [
                sys.executable,
                "-bb",
                "-c",
                "from sci_etl_core.search.filters import encode_metadata; print(encode_metadata({'b': b'abc'}))",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            timeout=120,
            check=True,
        )
        assert result.stdout.strip() == '{"b": "b\'abc\'"}'

    def test_any_other_object_is_rendered_through_str(self):
        class Survey:
            def __str__(self) -> str:
                return "SDSS DR17"

        assert json.loads(encode_metadata({"survey": Survey()})) == {"survey": "SDSS DR17"}

    def test_non_ascii_text_stays_readable(self):
        assert encode_metadata({"author": "Müller"}) == '{"author": "Müller"}'

    def test_a_lone_surrogate_is_escaped_so_the_text_can_be_stored(self):
        encoded = encode_metadata({"title": "a\ud800b"})
        encoded.encode("utf-8")
        assert json.loads(encoded) == {"title": "a\ud800b"}


def test_sanitize_text_replaces_controls_and_surrogates_but_keeps_tabs_and_line_breaks():
    assert sanitize_text("a\x00b\x02c\x03d\x1fe\tf\ng\rh\ud800i\x7fj") == "a b c d e\tf\ng\rh i\x7fj"


class TestBM25Weights:
    def test_defaults_weight_the_title_most(self):
        assert BM25Weights() == BM25Weights(title=10.0, abstract=4.0, body=1.0)

    @pytest.mark.parametrize("weights", [{"title": -1.0}, {"abstract": float("nan")}, {"body": float("inf")}])
    def test_a_negative_or_non_finite_weight_is_rejected(self, weights):
        with pytest.raises(ValueError, match="must be a finite number that is not negative"):
            BM25Weights(**weights)
