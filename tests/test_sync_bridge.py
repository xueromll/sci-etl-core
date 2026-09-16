from __future__ import annotations

import asyncio
import concurrent.futures
import threading

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


class TestWaiting:
    def test_bridge_loop_is_the_loop_run_sync_uses(self):
        async def running_loop():
            return asyncio.get_running_loop()

        assert _sync_bridge.run_sync(running_loop()) is _sync_bridge.bridge_loop()

    def test_a_timeout_error_raised_by_the_coroutine_is_not_reported_as_a_bridge_timeout(self):
        async def times_out():
            raise TimeoutError("inner")

        with pytest.raises(TimeoutError, match="inner"):
            _sync_bridge.run_sync(times_out(), timeout=5)

    def test_a_settled_future_holding_a_futures_timeout_error_is_not_reported_as_a_bridge_timeout(self, mocker):
        settled: concurrent.futures.Future[None] = concurrent.futures.Future()
        settled.set_exception(concurrent.futures.TimeoutError("inner"))
        mocker.patch.object(_sync_bridge.asyncio, "run_coroutine_threadsafe", return_value=settled)

        async def never_scheduled():
            return None

        coroutine = never_scheduled()
        try:
            with pytest.raises(concurrent.futures.TimeoutError, match="inner"):
                _sync_bridge.run_sync(coroutine, timeout=5)
        finally:
            coroutine.close()

    def test_a_slow_call_times_out_across_several_wait_slices(self, mocker):
        mocker.patch.object(_sync_bridge, "_WAIT_SLICE", 0.01)
        started = threading.Event()
        cancelled = threading.Event()

        async def slow():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with pytest.raises(TimeoutError, match="did not complete within 0.05 seconds"):
            _sync_bridge.run_sync(slow(), timeout=0.05)
        assert cancelled.wait(timeout=2)

    def test_an_interrupt_of_the_waiting_thread_cancels_the_bridge_task(self, mocker):
        cancelled = threading.Event()
        started = threading.Event()

        async def slow():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        real_future = asyncio.run_coroutine_threadsafe

        def interrupting(coro, loop):
            future = real_future(coro, loop)
            original_result = future.result

            def result(timeout=None):
                started.wait(timeout=2)
                if not future.done():
                    raise KeyboardInterrupt
                return original_result(timeout)

            future.result = result
            return future

        mocker.patch.object(_sync_bridge.asyncio, "run_coroutine_threadsafe", side_effect=interrupting)
        with pytest.raises(KeyboardInterrupt):
            _sync_bridge.run_sync(slow(), timeout=5)
        assert cancelled.wait(timeout=2)
