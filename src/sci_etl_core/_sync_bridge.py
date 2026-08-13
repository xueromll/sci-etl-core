from __future__ import annotations

import asyncio
import atexit
import threading
from typing import Any, Awaitable, Callable, Coroutine, TypeVar

T = TypeVar("T")

_THREAD_NAME = "sci-etl-sync-bridge"
_SHUTDOWN_TIMEOUT = 5.0


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


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on the shared bridge loop and block until it resolves."""
    return asyncio.run_coroutine_threadsafe(coro, _BRIDGE.loop()).result()


def to_async(func: Callable[..., T]) -> Callable[..., Awaitable[T]]:
    """Adapt a blocking callable into a coroutine function backed by a worker thread."""

    async def _invoke(*args: Any, **kwargs: Any) -> T:
        return await asyncio.to_thread(func, *args, **kwargs)

    return _invoke


def shutdown_bridge() -> None:
    """Stop and dispose the shared bridge loop; a later call restarts it."""
    _BRIDGE.shutdown()


atexit.register(shutdown_bridge)