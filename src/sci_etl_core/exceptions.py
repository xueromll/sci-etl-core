class SciEtlError(Exception):
    """Base exception for all sci-etl-core errors."""


class ExtractionError(SciEtlError):
    """Raised when a source extractor fails to retrieve or parse data."""


class ParsingError(SciEtlError):
    """Raised when a document parser fails to extract content."""


class LLMError(SciEtlError):
    """Raised when an LLM client call fails irrecoverably."""


class ConfigurationError(SciEtlError):
    """Raised when configuration loading or validation fails."""
