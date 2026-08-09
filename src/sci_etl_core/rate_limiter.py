from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from types import TracebackType


class AsyncRateLimiter(ABC):
    """Async context manager that gates concurrent access to a resource."""

    @abstractmethod
    async def __aenter__(self) -> "AsyncRateLimiter":
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

    async def __aenter__(self) -> "NullRateLimiter":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class SemaphoreRateLimiter(AsyncRateLimiter):
    """Bound concurrency to a fixed number of simultaneous slots."""

    def __init__(self, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self) -> "SemaphoreRateLimiter":
        await self._semaphore.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._semaphore.release()


class AioLimiterRateLimiter(AsyncRateLimiter):
    """Token-bucket limiter backed by the optional ``aiolimiter`` package."""

    def __init__(self, max_rate: float, time_period: float = 1.0) -> None:
        from aiolimiter import AsyncLimiter

        self._limiter = AsyncLimiter(max_rate, time_period)

    async def __aenter__(self) -> "AioLimiterRateLimiter":
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
