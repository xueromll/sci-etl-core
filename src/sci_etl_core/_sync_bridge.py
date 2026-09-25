from __future__ import annotations

import asyncio
import atexit
import math
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, TypeVar

T = TypeVar("T")

_THREAD_NAME = "sci-etl-sync-bridge"
_SHUTDOWN_TIMEOUT = 5.0
_DEFAULT_CALL_TIMEOUT: float | None = 300.0
_WAIT_SLICE = 0.2


class _BridgeLoop:
    """A lazily started daemon-thread event loop shared by all sync facades.

    A single long-lived loop is used instead of ``asyncio.run`` per call so that
    loop-bound resources (``httpx.AsyncClient`` pools, ``AsyncOpenAI`` sessions,
    ``asyncio.Lock``) stay valid across calls. Because the loop lives on its own
    thread, ``run_sync`` also works when the caller is already inside a running
    event loop.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._guard = threading.Lock()

    def loop(self) -> asyncio.AbstractEventLoop:
        with self._guard:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._serve, args=(self._loop,), name=_THREAD_NAME, daemon=True
                )
                self._thread.start()
            return self._loop

    @staticmethod
    def _serve(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def shutdown(self) -> None:
        with self._guard:
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=_SHUTDOWN_TIMEOUT)
        loop.close()


_BRIDGE = _BridgeLoop()
_default_timeout: float | None = _DEFAULT_CALL_TIMEOUT


def set_default_timeout(timeout: float | None) -> None:
    """Set the ceiling applied by :func:`run_sync` when no timeout is passed."""
    global _default_timeout
    _default_timeout = timeout


def run_sync(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """Run a coroutine on the shared bridge loop and block until it resolves.

    ``timeout`` falls back to the module default when omitted; pass ``math.inf``
    to wait indefinitely. The caller waits in short slices, so a signal handler
    on the calling thread runs promptly even on Windows. When the wait ends
    with an exception of the caller's own, such as ``KeyboardInterrupt``, the
    task on the bridge loop is cancelled before it propagates.

    Raises:
        TimeoutError: The coroutine did not settle within the ceiling. The
            underlying task is cancelled before the error propagates, so a
            wedged call can never pin the caller forever.
    """
    limit = _default_timeout if timeout is None else timeout
    deadline = None if limit is None or math.isinf(limit) else time.monotonic() + limit
    future = asyncio.run_coroutine_threadsafe(coro, _BRIDGE.loop())
    try:
        while True:
            remaining = _WAIT_SLICE if deadline is None else min(_WAIT_SLICE, deadline - time.monotonic())
            try:
                return future.result(max(remaining, 0.0))
            except FutureTimeoutError:
                if future.done():
                    raise
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"Bridge call did not complete within {limit} seconds")
    except BaseException:
        future.cancel()
        raise


def bridge_loop() -> asyncio.AbstractEventLoop:
    """Return the shared bridge loop, starting it if needed."""
    return _BRIDGE.loop()


def to_async(func: Callable[..., T]) -> Callable[..., Awaitable[T]]:
    """Adapt a blocking callable into a coroutine function backed by a worker thread."""

    async def _invoke(*args: Any, **kwargs: Any) -> T:
        return await asyncio.to_thread(func, *args, **kwargs)

    return _invoke


def shutdown_bridge() -> None:
    """Stop and dispose the shared bridge loop; a later call restarts it."""
    _BRIDGE.shutdown()


atexit.register(shutdown_bridge)
