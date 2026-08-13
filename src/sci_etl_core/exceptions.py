from __future__ import annotations


class SciEtlError(Exception):
    """Base exception for all sci-etl-core errors."""


class ExtractionError(SciEtlError):
    """Raised when a source extractor fails to retrieve or parse data."""


class UpstreamError(ExtractionError):
    """Raised when a remote source is unreachable or answers with a server error.

    Distinguishes a transport-level failure from a well-formed response that
    simply contains no further results.
    """


class MalformedResponseError(ExtractionError):
    """Raised when a listing payload cannot be interpreted as a valid feed.

    Distinguishes an unparseable payload from a valid but empty listing, which
    legitimately signals the end of available data.
    """


class ParsingError(SciEtlError):
    """Raised when a document parser fails to extract content."""


class LLMError(SciEtlError):
    """Raised when an LLM client call fails irrecoverably."""


class ConfigurationError(SciEtlError):
    """Raised when configuration loading or validation fails."""


class PipelineAborted(SciEtlError):
    """Raised when a pipeline run terminates early because of an upstream fault.

    Carries the number of records successfully processed before the abort so
    callers can distinguish partial progress from a run that never started.
    """

    def __init__(self, message: str, partial_count: int = 0) -> None:
        super().__init__(f"{message} (records processed before abort: {partial_count})")
        self.partial_count = partial_count
