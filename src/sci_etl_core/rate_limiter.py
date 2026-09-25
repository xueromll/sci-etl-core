from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import TracebackType
from typing import TypeAlias
from urllib.parse import urlsplit


class AsyncRateLimiter(ABC):
    """Async context manager that gates concurrent access to a resource."""

    @abstractmethod
    async def __aenter__(self) -> AsyncRateLimiter:
        """Acquire a slot, awaiting until one becomes available."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the previously acquired slot."""


class NullRateLimiter(AsyncRateLimiter):
    """No-op limiter that imposes no concurrency or rate constraint."""

    async def __aenter__(self) -> NullRateLimiter:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class SemaphoreRateLimiter(AsyncRateLimiter):
    """Bound concurrency to a fixed number of simultaneous slots.

    The slot is released from a ``finally`` block so bookkeeping failures or a
    cancellation delivered during exit can never permanently consume a slot.
    """

    def __init__(self, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._held = 0

    @property
    def held(self) -> int:
        """Number of slots currently checked out."""
        return self._held

    async def __aenter__(self) -> SemaphoreRateLimiter:
        await self._semaphore.acquire()
        try:
            self._held += 1
        except BaseException:
            self._semaphore.release()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            self._held -= 1
        finally:
            self._semaphore.release()


class AioLimiterRateLimiter(AsyncRateLimiter):
    """Token-bucket limiter backed by the optional ``aiolimiter`` package."""

    def __init__(self, max_rate: float, time_period: float = 1.0) -> None:
        from aiolimiter import AsyncLimiter

        self._limiter = AsyncLimiter(max_rate, time_period)

    async def __aenter__(self) -> AioLimiterRateLimiter:
        await self._limiter.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._limiter.__aexit__(exc_type, exc, tb)


def build_rate_limiter(
    max_concurrency: int = 4,
    max_rate: float | None = None,
    time_period: float = 1.0,
) -> AsyncRateLimiter:
    """Build a limiter, preferring a semaphore unless a rate cap is supplied."""
    if max_rate is not None:
        return AioLimiterRateLimiter(max_rate=max_rate, time_period=time_period)
    return SemaphoreRateLimiter(max_concurrency=max_concurrency)


class HostRateLimiter:
    """Pick a limiter by the host a request goes to.

    A request's host is matched against the configured hosts from the most
    specific name down, so ``"arxiv.org"`` also covers ``export.arxiv.org``
    unless that host has a limiter of its own. Host names match without regard
    to case. A request to a host with no match uses ``default``, which imposes
    no limit when omitted. Pass one instance to several components to have
    them share each host's budget.
    """

    def __init__(
        self,
        limiters: Mapping[str, AsyncRateLimiter],
        default: AsyncRateLimiter | None = None,
    ) -> None:
        """Store the limiter for each host.

        Raises:
            ValueError: A host is blank, or two hosts differ only in case or
                surrounding dots.
        """
        normalized: dict[str, AsyncRateLimiter] = {}
        for host, limiter in limiters.items():
            key = host.strip().strip(".").lower()
            if not key:
                raise ValueError("Rate-limited host names must not be blank")
            if key in normalized:
                raise ValueError(f"Host {key!r} is configured more than once")
            normalized[key] = limiter
        self._limiters = normalized
        self._default = default or NullRateLimiter()

    def for_url(self, url: str) -> AsyncRateLimiter:
        """Return the limiter governing requests to ``url``."""
        host = (urlsplit(url).hostname or "").rstrip(".")
        labels = host.split(".")
        for start in range(len(labels)):
            limiter = self._limiters.get(".".join(labels[start:]))
            if limiter is not None:
                return limiter
        return self._default


RateLimiting: TypeAlias = AsyncRateLimiter | HostRateLimiter


def limiter_for(rate_limiter: RateLimiting | None, url: str) -> AsyncRateLimiter:
    """Resolve the limiter a component applies to a request for ``url``."""
    if rate_limiter is None:
        return _UNLIMITED
    if isinstance(rate_limiter, HostRateLimiter):
        return rate_limiter.for_url(url)
    return rate_limiter


_UNLIMITED = NullRateLimiter()
