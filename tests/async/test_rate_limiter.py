from __future__ import annotations

import asyncio
import sys
import types

import pytest

from sci_etl_core.rate_limiter import (
    AioLimiterRateLimiter,
    AsyncRateLimiter,
    NullRateLimiter,
    SemaphoreRateLimiter,
    build_rate_limiter,
)


class _FakeAsyncLimiter:
    def __init__(self, max_rate: float, time_period: float = 1.0) -> None:
        self.max_rate = max_rate
        self.time_period = time_period
        self.events: list[str] = []

    async def __aenter__(self) -> "_FakeAsyncLimiter":
        self.events.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.events.append("exit")


@pytest.fixture
def fake_aiolimiter(mocker):
    module = types.ModuleType("aiolimiter")
    module.AsyncLimiter = _FakeAsyncLimiter
    mocker.patch.dict(sys.modules, {"aiolimiter": module})
    return module


class TestNullRateLimiter:
    @pytest.mark.asyncio
    async def test_enters_and_exits_without_blocking(self):
        limiter = NullRateLimiter()
        async with limiter as entered:
            assert entered is limiter
        assert await limiter.__aexit__(None, None, None) is None


class TestSemaphoreRateLimiter:
    @pytest.mark.asyncio
    async def test_caps_concurrency(self):
        limiter = SemaphoreRateLimiter(max_concurrency=2)
        active = peak = 0

        async def task():
            nonlocal active, peak
            async with limiter:
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(task() for _ in range(6)))
        assert peak <= 2

    def test_rejects_non_positive_concurrency(self):
        with pytest.raises(ValueError):
            SemaphoreRateLimiter(max_concurrency=0)


class TestAioLimiterRateLimiter:
    @pytest.mark.asyncio
    async def test_delegates_to_aiolimiter(self, fake_aiolimiter):
        limiter = AioLimiterRateLimiter(max_rate=5, time_period=2.0)
        assert limiter._limiter.max_rate == 5
        assert limiter._limiter.time_period == 2.0
        async with limiter as entered:
            assert entered is limiter
        assert limiter._limiter.events == ["enter", "exit"]


class TestBuildRateLimiter:
    def test_defaults_to_semaphore(self):
        limiter = build_rate_limiter(max_concurrency=3)
        assert isinstance(limiter, SemaphoreRateLimiter)
        assert isinstance(limiter, AsyncRateLimiter)

    def test_returns_aiolimiter_when_rate_supplied(self, fake_aiolimiter):
        limiter = build_rate_limiter(max_rate=10, time_period=1.0)
        assert isinstance(limiter, AioLimiterRateLimiter)
