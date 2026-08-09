from __future__ import annotations

import re

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from sci_etl_core.extractors.arxiv import ArxivExtractor
from sci_etl_core.parsers.reference_trimmer import trim_after_references
from sci_etl_core.processors.normalization import DefaultKeyNormalizer

_EXTRACTOR = ArxivExtractor(client=None, pdf_parser=None, latex_parser=None)
_NORMALIZER = DefaultKeyNormalizer()

_ARXIV_ID = st.from_regex(r"[0-9]{4}\.[0-9]{4,5}(v[0-9]+)?", fullmatch=True)
_NO_MARKER_TEXT = st.text(st.characters(blacklist_characters="\n\r\\"))


class TestNormalizeIdProperties:
    @given(_ARXIV_ID)
    def test_bare_id_is_returned_unchanged(self, bare):
        assert _EXTRACTOR._normalize_id(bare) == bare

    @given(_ARXIV_ID)
    def test_abs_prefix_is_stripped(self, bare):
        assert _EXTRACTOR._normalize_id(f"http://arxiv.org/abs/{bare}") == bare

    @given(_ARXIV_ID)
    def test_pdf_prefix_and_suffix_are_stripped(self, bare):
        assert _EXTRACTOR._normalize_id(f"http://arxiv.org/pdf/{bare}.pdf") == bare

    @given(st.text())
    def test_result_never_retains_an_abs_marker(self, raw):
        assert "/abs/" not in _EXTRACTOR._normalize_id(raw)


class TestTrimAfterReferencesProperties:
    @given(st.text())
    def test_result_is_a_prefix_of_the_input(self, text):
        result = trim_after_references(text)
        assert text.startswith(result)

    @given(st.text())
    def test_result_is_never_longer_than_input(self, text):
        assert len(trim_after_references(text)) <= len(text)

    @given(_NO_MARKER_TEXT)
    def test_text_without_markers_is_unchanged(self, text):
        assert trim_after_references(text) == text

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_values_pass_through(self, empty):
        assert trim_after_references(empty) == empty


class TestDefaultKeyNormalizerProperties:
    @given(st.text())
    def test_output_contains_only_lowercase_alphanumerics(self, raw):
        assert re.fullmatch(r"[a-z0-9]*", _NORMALIZER.normalize(raw))

    @given(st.text())
    def test_normalize_is_idempotent(self, raw):
        once = _NORMALIZER.normalize(raw)
        assert _NORMALIZER.normalize(once) == once

    @given(st.text())
    def test_output_equals_its_own_lowercase(self, raw):
        result = _NORMALIZER.normalize(raw)
        assert result == result.lower()
