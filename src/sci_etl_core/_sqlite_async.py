from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class AsyncSqliteRunner:
    """Serialize blocking sqlite3 work onto a worker thread, safely under cancellation.

    Holds one connection and one :class:`asyncio.Lock`. Every operation runs to
    completion on its thread even if the awaiting task is cancelled, so a second
    task can never take the connection while the first is still using it.

    ``open_connection`` opens, configures, and bootstraps the connection on the
    worker thread when it is first needed, and again after :meth:`aclose`. With
    ``error_factory=None`` a :class:`sqlite3.Error` raised by an operation
    propagates unchanged; otherwise it is replaced by
    ``error_factory("Failed to <action>: <error>")``, chained to the original.
    """

    def __init__(
        self,
        open_connection: Callable[[], sqlite3.Connection],
        *,
        error_factory: Callable[[str], Exception] | None,
    ) -> None:
        self._open_connection = open_connection
        self._error_factory = error_factory
        self._connection: sqlite3.Connection | None = None
        self._lock: asyncio.Lock | None = None

    async def run(self, operation: Callable[[sqlite3.Connection], T], action: str) -> T:
        """Run ``operation`` on the connection in a worker thread and return its result.

        Operations run one at a time. The lock is created on first use, so a
        runner can be constructed outside a running event loop, but it binds to
        the loop that first contends for it: use each runner from one loop only.
        An exception other than :class:`sqlite3.Error` from ``open_connection``
        or ``operation`` propagates unchanged.

        Raises:
            asyncio.CancelledError: The awaiting task was cancelled. Once
                ``operation`` has started, this is raised only after it finishes
                on its thread, and whatever it raised meanwhile is discarded.
            sqlite3.Error: Opening the connection or running ``operation`` failed
                and there is no ``error_factory``; with one, the error raised is
                ``error_factory("Failed to <action>: <error>")``.
        """
        async with self._get_lock():
            work = asyncio.ensure_future(asyncio.to_thread(self._execute, operation))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                await asyncio.wait({work})
                if not work.cancelled():
                    work.exception()
                raise
            except sqlite3.Error as exc:
                if self._error_factory is None:
                    raise
                raise self._error_factory(f"Failed to {action}: {exc}") from exc

    async def aclose(self) -> None:
        """Close the connection; a later :meth:`run` transparently reopens it."""
        async with self._get_lock():
            connection, self._connection = self._connection, None
        if connection is not None:
            await asyncio.to_thread(connection.close)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _execute(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        if self._connection is None:
            self._connection = self._open_connection()
        return operation(self._connection)
