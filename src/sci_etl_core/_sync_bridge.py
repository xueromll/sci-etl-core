from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, TypeVar

_T = TypeVar("_T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is not None and not _loop.is_closed():
        return _loop
    with _lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="sci-etl-sync", daemon=True)
            thread.start()
            _loop = loop
    return _loop


def run_sync(awaitable: Awaitable[_T]) -> _T:
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(_await(awaitable), loop)
    return future.result()


async def _await(awaitable: Awaitable[_T]) -> _T:
    return await awaitable
