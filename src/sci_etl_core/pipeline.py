from __future__ import annotations

import math
from contextlib import suppress
from typing import Any, Coroutine

from sci_etl_core._sync_bridge import run_sync
from sci_etl_core.pipeline_async import AsyncETLPipeline

_CLOSE_TIMEOUT = 30.0


class ETLPipeline:
    """Synchronous facade for :class:`AsyncETLPipeline`.

    The only blocking entrypoint. All collaborators injected into the
    constructor must be async implementations. A full run is unbounded by
    default; ``run_timeout`` imposes a ceiling when the caller wants one.
    """

    def __init__(self, *args: Any, run_timeout: float = math.inf, **kwargs: Any) -> None:
        self._async = AsyncETLPipeline(*args, **kwargs)
        self._run_timeout = run_timeout

    def run(self, *args: Any, **kwargs: Any) -> int:
        return run_sync(self._async.run(*args, **kwargs), timeout=self._run_timeout)

    def __enter__(self) -> "ETLPipeline":
        return self

    def __exit__(self, *exc: Any) -> None:
        for resource in self._async.closeables:
            aclose = getattr(resource, "aclose", None)
            if aclose is not None:
                self._close(aclose())

    def _close(self, closing: Coroutine[Any, Any, Any]) -> None:
        """Await a close coroutine, tolerating an already-disposed bridge loop.

        Teardown must never mask the exception that triggered it, so a stopped
        or closed loop is logged and skipped instead of propagated.
        """
        try:
            run_sync(closing, timeout=_CLOSE_TIMEOUT)
        except (RuntimeError, TimeoutError) as error:
            with suppress(RuntimeError):
                closing.close()
            self._async.log(f"Resource close skipped: {error!r}")
