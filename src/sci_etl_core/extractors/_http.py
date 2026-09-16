from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Callable

import httpx

from sci_etl_core._retry_after import retry_after_from_headers, retry_delay
from sci_etl_core.exceptions import ExtractionError, ParsingError, UpstreamError
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.rate_limiter import RateLimiting, limiter_for

_RETRYABLE_STATUS = frozenset({408, 429})
_SERVER_ERROR_FLOOR = 500


class RetryingFetcher:
    """GET requests with the retry, ``Retry-After``, and rate-limit behavior every bundled extractor shares.

    Transport faults, ``408``, ``429``, and server errors are retried, waiting
    ``backoff_factor ** attempt`` seconds or longer when the response's
    ``Retry-After`` asks, up to ``max_retry_after``. Each attempt enters the
    rate limiter for its URL and releases it once the response arrives.
    Redirects are followed.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        source: str,
        *,
        max_retries: int,
        backoff_factor: float,
        max_retry_after: float,
        sleep: Any,
        logger: Callable[[str], None],
        rate_limiter: RateLimiting | None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be a positive integer")
        if max_retry_after < 0:
            raise ValueError("max_retry_after must not be negative")
        self._client = client
        self._source = source
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._max_retry_after = max_retry_after
        self._sleep = sleep
        self._log = logger
        self._rate_limiter = rate_limiter
        self._headers = dict(headers or {})

    async def fetch(self, url: str, action: str, params: Mapping[str, Any] | None = None) -> bytes:
        """Return the body of a successful response.

        Raises:
            UpstreamError: Every attempt failed transiently.
            ExtractionError: The source rejected the request with a status that
                retrying cannot fix, such as ``400``.
        """
        response = await self._get(url, action, params)
        if not response.is_success:
            raise ExtractionError(f"{self._source} rejected the {action} with status {response.status_code}")
        return response.content

    async def fetch_optional(self, url: str, action: str, params: Mapping[str, Any] | None = None) -> bytes | None:
        """Return the body of a successful response, or ``None`` when the source says it will never succeed.

        Raises:
            UpstreamError: Every attempt failed transiently.
        """
        response = await self._get(url, action, params)
        if not response.is_success:
            self._log(f"{self._source} {action} unavailable: status {response.status_code}")
            return None
        return response.content

    async def _get(self, url: str, action: str, params: Mapping[str, Any] | None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            retry_after: float | None = None
            try:
                async with limiter_for(self._rate_limiter, url):
                    response = await self._client.get(
                        url, params=params, headers=self._headers, follow_redirects=True
                    )
            except httpx.RequestError as exc:
                last_error = exc
            else:
                if response.is_success or not _retryable(response.status_code):
                    return response
                last_error = UpstreamError(f"{self._source} returned status {response.status_code}")
                retry_after = retry_after_from_headers(response.headers)
            if attempt < self._max_retries - 1:
                delay = retry_delay(attempt, self._backoff_factor, retry_after, self._max_retry_after)
                self._log(
                    f"{self._source} {action} attempt {attempt + 1} failed ({last_error!r}); retrying in {delay:g} s"
                )
                await self._sleep(delay)
        message = f"{self._source} {action} failed after {self._max_retries} attempts"
        self._log(f"{message}: {last_error!r}")
        raise UpstreamError(message) from last_error


async def parse_document(
    parser: Parser, content: bytes, label: str, record: RawRecord, log: Callable[[str], None]
) -> str:
    """Parse a fetched document off the event loop, treating an unreadable one as unavailable."""
    try:
        text = await asyncio.to_thread(parser.extract_text, content)
    except ParsingError as exc:
        log(f"{label} unusable for {record.record_id!r}: {exc}")
        return ""
    return text.strip()


def _retryable(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS or status_code >= _SERVER_ERROR_FLOOR
