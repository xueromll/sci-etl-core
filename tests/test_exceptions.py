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
    ],
)
def test_hierarchy(error, ancestor):
    assert issubclass(error, ancestor)


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
