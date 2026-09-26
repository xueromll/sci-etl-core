from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from sci_etl_core._retry_after import retry_after_from_headers, retry_delay
from sci_etl_core.exceptions import ExtractionError, ParsingError, UpstreamError
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.rate_limiter import RateLimiting, limiter_for

_RETRYABLE_STATUS = frozenset({408, 429})
_SERVER_ERROR_FLOOR = 500
_SUCCESS_FLOOR = 200
_SUCCESS_CEILING = 300


class ResponseTooLarge(ExtractionError):
    """A response body grew past the fetcher's ``max_bytes``; retrying cannot fix it."""


@dataclass(frozen=True, slots=True)
class FetchedResponse:
    """A response whose body has been read in full, within the fetcher's size limit."""

    status_code: int
    headers: httpx.Headers
    content: bytes

    @property
    def is_success(self) -> bool:
        return _SUCCESS_FLOOR <= self.status_code < _SUCCESS_CEILING


class RetryingFetcher:
    """GET requests with the retry, ``Retry-After``, and rate-limit behavior every bundled extractor shares.

    Transport faults, ``408``, ``429``, and server errors are retried, waiting
    ``backoff_factor ** attempt`` seconds or longer when the response's
    ``Retry-After`` asks, up to ``max_retry_after``. Each attempt enters the
    rate limiter for its URL and releases it once the response body has been
    read. Redirects are followed.

    With ``max_bytes``, a body is read only up to that many bytes after
    decoding, so neither a huge download nor a compressed response that
    expands without bound can exhaust memory. A larger body raises
    :class:`ResponseTooLarge` and is not retried.
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
        max_bytes: int | None = None,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be a positive integer")
        if max_retry_after < 0:
            raise ValueError("max_retry_after must not be negative")
        if max_bytes is not None and max_bytes < 1:
            raise ValueError("max_download_bytes must be a positive integer")
        self._client = client
        self._source = source
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._max_retry_after = max_retry_after
        self._sleep = sleep
        self._log = logger
        self._rate_limiter = rate_limiter
        self._headers = dict(headers or {})
        self._max_bytes = max_bytes

    async def fetch(self, url: str, action: str, params: Mapping[str, Any] | None = None) -> bytes:
        """Return the body of a successful response.

        Raises:
            UpstreamError: Every attempt failed transiently.
            ExtractionError: The source rejected the request with a status that
                retrying cannot fix, such as ``400``, or the body exceeds
                ``max_bytes`` (:class:`ResponseTooLarge`).
        """
        response = await self._get(url, action, params)
        if not response.is_success:
            raise ExtractionError(f"{self._source} rejected the {action} with status {response.status_code}")
        return response.content

    async def response(self, url: str, action: str, params: Mapping[str, Any] | None = None) -> FetchedResponse:
        """Return the final response, successful or a status that retrying cannot fix.

        Raises:
            UpstreamError: Every attempt failed transiently.
            ResponseTooLarge: The body exceeds ``max_bytes``.
        """
        return await self._get(url, action, params)

    async def fetch_optional(self, url: str, action: str, params: Mapping[str, Any] | None = None) -> bytes | None:
        """Return the body of a successful response, or ``None`` when it will never be usable.

        That is when the source answers with a status that retrying cannot fix,
        or the body exceeds ``max_bytes``; either is logged.

        Raises:
            UpstreamError: Every attempt failed transiently.
        """
        try:
            response = await self._get(url, action, params)
        except ResponseTooLarge as exc:
            self._log(f"{self._source} {action} unavailable: {exc}")
            return None
        if not response.is_success:
            self._log(f"{self._source} {action} unavailable: status {response.status_code}")
            return None
        return response.content

    async def _download(self, url: str, params: Mapping[str, Any] | None) -> FetchedResponse:
        async with self._client.stream(
            "GET", url, params=params, headers=self._headers, follow_redirects=True
        ) as response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if self._max_bytes is not None and size > self._max_bytes:
                    raise ResponseTooLarge(f"response body exceeds {self._max_bytes} bytes")
                chunks.append(chunk)
        return FetchedResponse(response.status_code, response.headers, b"".join(chunks))

    async def _get(self, url: str, action: str, params: Mapping[str, Any] | None) -> FetchedResponse:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            retry_after: float | None = None
            try:
                async with limiter_for(self._rate_limiter, url):
                    response = await self._download(url, params)
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
