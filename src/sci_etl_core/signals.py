from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from types import FrameType
from typing import Any

from sci_etl_core._deprecation import warn_logger_argument

DEFAULT_SIGNALS: tuple[signal.Signals, ...] = tuple(
    member
    for member in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None))
    if member is not None
)


class ShutdownSignal:
    """Cooperative shutdown flag driven by OS termination signals.

    The first signal sets the flag so the owner can flush pending state. A
    second signal restores the previous handler and re-raises, letting the
    default hard termination proceed. Handlers are installed only from the main
    thread, so the synchronous bridge loop is unaffected, and the exact handler
    in force beforehand is put back on exit.

    Pass one to :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` or
    :class:`~sci_etl_core.pipeline.ETLPipeline` as ``shutdown`` and the pipeline
    installs the handlers for each run and stops cleanly when the flag is set.
    """

    def __init__(
        self,
        signals: Iterable[signal.Signals] = DEFAULT_SIGNALS,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        warn_logger_argument("ShutdownSignal", logger)
        self._signals = tuple(signals)
        self._log = logger or (lambda _msg: None)
        self._event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_handled: set[signal.Signals] = set()
        self._previous: dict[signal.Signals, Any] = {}
        self._depth = 0
        self._depth_lock = threading.Lock()

    @property
    def triggered(self) -> bool:
        """Whether a graceful shutdown has been requested."""
        return self._event.is_set()

    async def wait(self) -> None:
        """Block until a shutdown is requested."""
        await self._event.wait()

    def request(self) -> None:
        """Request shutdown programmatically, as if a signal had arrived."""
        self._event.set()

    @contextmanager
    def guard(self, loop: asyncio.AbstractEventLoop | None = None) -> Iterator[ShutdownSignal]:
        """Install handlers for the duration of the block and restore them after.

        Guards nest: only the outermost block installs and restores handlers, so
        a pipeline given this signal can run inside a caller's own guard.
        ``loop`` is passed to :meth:`install`.
        """
        with self._depth_lock:
            outermost = self._depth == 0
            self._depth += 1
        try:
            if outermost:
                self.install(loop)
            yield self
        finally:
            with self._depth_lock:
                self._depth -= 1
            if outermost:
                self.uninstall()

    def install(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Install the handlers from the main thread.

        Without ``loop``, the handlers serve the running event loop. With
        ``loop``, plain OS handlers set the flag on that loop, which may run on
        another thread; this lets a thread that blocks while a background loop
        does the work, as :class:`~sci_etl_core.pipeline.ETLPipeline` does,
        receive signals for it.
        """
        serves_running_loop = loop is None
        self._loop = asyncio.get_running_loop() if loop is None else loop
        if threading.current_thread() is not threading.main_thread():
            self._log("Shutdown handlers skipped: not running on the main thread")
            return
        for member in self._signals:
            if serves_running_loop:
                self._install_one(member)
            else:
                self._capture_previous(member)
                self._install_os_handler(member)

    def uninstall(self) -> None:
        """Remove the handlers :meth:`install` added and restore the ones they replaced."""
        for member in tuple(self._loop_handled):
            self._remove_loop_handler(member)
        for member, previous in tuple(self._previous.items()):
            self._restore_os_handler(member, previous)
        self._loop = None

    def _install_one(self, member: signal.Signals) -> None:
        loop = self._loop
        if loop is None:
            return
        self._capture_previous(member)
        try:
            loop.add_signal_handler(member, self._on_loop_signal, member)
        except (AttributeError, NotImplementedError, RuntimeError, ValueError):
            self._install_os_handler(member)
        else:
            self._loop_handled.add(member)

    def _capture_previous(self, member: signal.Signals) -> None:
        """Record the handler in force before installation.

        ``loop.remove_signal_handler`` resets ``SIGINT`` to the interpreter
        default rather than to whatever the host application had installed, so
        the original is captured here and restored explicitly.
        """
        with suppress(OSError, ValueError):
            self._previous.setdefault(member, signal.getsignal(member))

    def _install_os_handler(self, member: signal.Signals) -> None:
        try:
            signal.signal(member, self._on_os_signal)
        except (OSError, ValueError):
            self._previous.pop(member, None)
            self._log(f"Shutdown handler unavailable for {member!r}")

    def _remove_loop_handler(self, member: signal.Signals) -> None:
        self._loop_handled.discard(member)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with suppress(NotImplementedError, RuntimeError, ValueError):
            loop.remove_signal_handler(member)

    def _restore_os_handler(self, member: signal.Signals, previous: Any) -> None:
        self._previous.pop(member, None)
        if previous is None:
            return
        with suppress(OSError, TypeError, ValueError):
            signal.signal(member, previous)

    def _on_loop_signal(self, member: signal.Signals) -> None:
        if self._event.is_set():
            self._escalate(member)
            return
        self._log(f"Received {member!r}; flushing state before shutdown")
        self._event.set()

    def _on_os_signal(self, signal_number: int, frame: FrameType | None) -> None:
        member = signal.Signals(signal_number)
        if self._event.is_set():
            self._escalate(member)
            return
        self._log(f"Received {member!r}; flushing state before shutdown")
        loop = self._loop
        if loop is None or loop.is_closed():
            self._event.set()
            return
        loop.call_soon_threadsafe(self._event.set)

    def _escalate(self, member: signal.Signals) -> None:
        self._log(f"Received {member!r} again; restoring default termination")
        self.uninstall()
        signal.raise_signal(member)
