from __future__ import annotations

ERROR_TEXT_LIMIT = 4096
TRUNCATION_MARKER = "… [truncated]"


def bounded_error_text(error: str) -> str:
    """Return ``error`` cut to :data:`ERROR_TEXT_LIMIT` characters, marker included, when it is longer."""
    if len(error) <= ERROR_TEXT_LIMIT:
        return error
    return error[: ERROR_TEXT_LIMIT - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
