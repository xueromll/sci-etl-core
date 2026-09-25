from __future__ import annotations

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any


def parse_retry_after(value: Any, now: datetime | None = None) -> float | None:
    """Return the wait a ``Retry-After`` header value asks for, in seconds.

    Both forms the header allows are accepted: a number of seconds and an HTTP
    date. A date in the past asks for no wait. Anything else, including a
    missing, negative or non-finite value, returns ``None``.
    """
    if not isinstance(value, str):
        return None
    seconds = _seconds(value)
    if seconds is not None:
        return seconds
    try:
        moment = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    reference = now if now is not None else datetime.now(UTC)
    return max((moment - reference).total_seconds(), 0.0)


def retry_after_from_headers(headers: Any) -> float | None:
    """Return the wait response headers ask for, in seconds.

    OpenAI-compatible APIs send ``retry-after-ms``, which is more precise than
    the standard ``Retry-After`` and is preferred when both are present.
    """
    get = getattr(headers, "get", None)
    if get is None:
        return None
    milliseconds = _seconds(get("retry-after-ms"))
    if milliseconds is not None:
        return milliseconds / 1000
    return parse_retry_after(get("retry-after"))


def retry_after_from_error(error: BaseException) -> float | None:
    """Return the wait asked for by the HTTP response attached to ``error``, if any."""
    return retry_after_from_headers(getattr(getattr(error, "response", None), "headers", None))


def retry_delay(attempt: int, backoff_factor: float, retry_after: float | None, max_retry_after: float) -> float:
    """Return how long to wait before the attempt after ``attempt``.

    The exponential backoff is the minimum. A server that asks for a longer
    wait gets it, capped at ``max_retry_after`` so that one response cannot
    stall a run indefinitely.
    """
    backoff = float(backoff_factor**attempt)
    if retry_after is None:
        return backoff
    return max(backoff, min(retry_after, max_retry_after))


def _seconds(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None
