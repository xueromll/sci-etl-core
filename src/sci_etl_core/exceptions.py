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


class StaleCursorError(ExtractionError):
    """Raised when a source no longer accepts a listing cursor it handed out earlier.

    :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` restarts the
    listing from its first page once per run when it sees this error.
    """


class ParsingError(SciEtlError):
    """Raised when a document parser fails to extract content."""


class LLMError(SciEtlError):
    """Raised when an LLM client call fails irrecoverably."""


class LLMCacheError(SciEtlError):
    """Raised when an LLM response cache cannot be read or written.

    Kept distinct from :class:`LLMError` so a cache fault is never mistaken for
    a failed completion; a caching client logs it and calls the LLM instead.
    """


class EmbeddingError(SciEtlError):
    """Raised when an embedding backend fails to vectorize text.

    Kept distinct from :class:`LLMError` so a semantic-similarity failure is
    never silently confused with a chat-completion failure.
    """


class EmbeddingStoreError(SciEtlError):
    """Raised when the vector memory cannot be written to or read from.

    Kept distinct from :class:`EmbeddingError` so a storage fault is never
    mistaken for a failure to produce the embedding itself.
    """


class SearchError(SciEtlError):
    """Raised when a text search operation fails."""


class SearchQueryError(SearchError):
    """Raised when a Boolean query cannot be parsed or cannot be run as asked.

    Kept distinct from :class:`SearchStoreError` so a typo in a query is never
    mistaken for a corrupt index. ``position`` is the character offset into the
    query at fault and ``token`` is the text found there, so a UI can underline
    it. ``position`` is ``None`` and ``token`` is empty when the error concerns
    the request rather than a character of the query.
    """

    def __init__(self, message: str, *, position: int | None = None, token: str = "") -> None:
        super().__init__(message)
        self.position = position
        self.token = token


class SearchStoreError(SearchError):
    """Raised when the text index cannot be read or written.

    Kept distinct from :class:`SearchQueryError` so a storage fault is never
    mistaken for a malformed query.
    """


class StateStoreError(SciEtlError):
    """Raised when a state file or database cannot be used as run state.

    A bundled state manager raises it for a file written by a newer
    sci-etl-core, whose schema version it does not know.
    """


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


class PipelineInterrupted(PipelineAborted):
    """Raised when a pipeline run stops early because a shutdown was requested.

    A subclass of :class:`PipelineAborted`, so code that already handles an
    abort keeps working. The records in flight when the request arrived were
    finished, the rest of their page is left for the next run, and state was
    flushed before this was raised.
    """
