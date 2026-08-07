from __future__ import annotations

import asyncio

import pytest

from sci_etl_core import _sync_bridge


async def _echo(value):
    await asyncio.sleep(0)
    return value


async def _boom():
    raise ValueError("boom")


class TestRunSync:
    def test_returns_the_coroutine_result(self):
        assert _sync_bridge.run_sync(_echo(7)) == 7

    def test_propagates_exceptions_to_the_caller(self):
        with pytest.raises(ValueError, match="boom"):
            _sync_bridge.run_sync(_boom())

    def test_reuses_a_single_loop(self):
        assert _sync_bridge._BRIDGE.loop() is _sync_bridge._BRIDGE.loop()

    def test_works_when_the_caller_already_runs_a_loop(self):
        async def outer():
            return await asyncio.to_thread(_sync_bridge.run_sync, _echo("nested"))

        assert asyncio.run(outer()) == "nested"


class TestToAsync:
    def test_wraps_a_blocking_callable(self):
        upper = _sync_bridge.to_async(str.upper)
        assert _sync_bridge.run_sync(upper("abc")) == "ABC"

    def test_forwards_keyword_arguments(self):
        joined = _sync_bridge.to_async(lambda *parts, sep="-": sep.join(parts))
        assert _sync_bridge.run_sync(joined("a", "b", sep="+")) == "a+b"


class TestShutdown:
    def test_shutdown_closes_the_loop_and_restarts_on_demand(self):
        loop = _sync_bridge._BRIDGE.loop()
        _sync_bridge.shutdown_bridge()
        assert loop.is_closed()
        _sync_bridge.shutdown_bridge()
        assert _sync_bridge.run_sync(_echo("restarted")) == "restarted"
