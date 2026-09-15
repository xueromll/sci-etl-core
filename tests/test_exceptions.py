from __future__ import annotations

import pytest

from sci_etl_core.exceptions import (
    ConfigurationError,
    ExtractionError,
    LLMError,
    MalformedResponseError,
    ParsingError,
    PipelineAborted,
    SciEtlError,
    SearchError,
    SearchQueryError,
    SearchStoreError,
    UpstreamError,
)


@pytest.mark.parametrize(
    "error, ancestor",
    [
        (UpstreamError, ExtractionError),
        (MalformedResponseError, ExtractionError),
        (ExtractionError, SciEtlError),
        (ParsingError, SciEtlError),
        (LLMError, SciEtlError),
        (ConfigurationError, SciEtlError),
        (PipelineAborted, SciEtlError),
        (SearchError, SciEtlError),
        (SearchQueryError, SearchError),
        (SearchStoreError, SearchError),
    ],
)
def test_hierarchy(error, ancestor):
    assert issubclass(error, ancestor)


def test_a_query_error_is_never_a_store_error():
    assert not issubclass(SearchQueryError, SearchStoreError)
    assert not issubclass(SearchStoreError, SearchQueryError)


class TestSearchQueryError:
    def test_carries_the_position_and_token_at_fault(self):
        error = SearchQueryError("Unknown field 'titel'", position=4, token="titel")
        assert (str(error), error.position, error.token) == ("Unknown field 'titel'", 4, "titel")

    def test_a_request_level_error_has_no_position(self):
        error = SearchQueryError("Semantic mode requires a finder")
        assert (error.position, error.token) == (None, "")


class TestPipelineAborted:
    def test_carries_the_partial_count(self):
        error = PipelineAborted("Listing fetch failed upstream", 12)
        assert error.partial_count == 12
        assert "12" in str(error)

    def test_defaults_to_zero_partial_records(self):
        assert PipelineAborted("nothing started").partial_count == 0

    def test_preserves_the_originating_cause(self):
        try:
            try:
                raise UpstreamError("gateway down")
            except UpstreamError as exc:
                raise PipelineAborted("Listing fetch failed upstream", 3) from exc
        except PipelineAborted as aborted:
            assert isinstance(aborted.__cause__, UpstreamError)
            assert aborted.partial_count == 3
