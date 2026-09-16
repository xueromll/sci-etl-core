from __future__ import annotations

import math
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Coroutine

from sci_etl_core._sync_bridge import bridge_loop, run_sync
from sci_etl_core.pipeline_async import AsyncETLPipeline

if TYPE_CHECKING:
    from sci_etl_core.config import PipelineConfig
    from sci_etl_core.observability import RunMetrics

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

    @classmethod
    def from_config(cls, pipeline: PipelineConfig, **arguments: Any) -> "ETLPipeline":
        """Build a pipeline configured as :meth:`AsyncETLPipeline.from_config` describes."""
        arguments.setdefault("max_concurrency", pipeline.max_concurrency)
        return cls(**arguments)

    def run(self, *args: Any, **kwargs: Any) -> int:
        """Run :meth:`AsyncETLPipeline.run` and block until it ends.

        With a ``shutdown`` signal, its handlers are installed on the calling
        thread, which must be the main thread for signals to reach them, and
        set the flag on the background loop, so Ctrl+C stops the run as
        described for the async pipeline.
        """
        shutdown = self._async.shutdown
        if shutdown is None:
            return run_sync(self._async.run(*args, **kwargs), timeout=self._run_timeout)
        with shutdown.guard(loop=bridge_loop()):
            return run_sync(self._async.run(*args, **kwargs), timeout=self._run_timeout)

    @property
    def last_run_metrics(self) -> RunMetrics | None:
        """Metrics of the most recent run, as :attr:`AsyncETLPipeline.last_run_metrics`."""
        return self._async.last_run_metrics

    def __enter__(self) -> "ETLPipeline":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Close every resource, even when an earlier one fails to close.

        A close failure is raised only when the block itself succeeded, so
        teardown never masks the exception that ended the block.
        """
        errors: list[Exception] = []
        for resource in self._async.closeables:
            aclose = getattr(resource, "aclose", None)
            if aclose is None:
                continue
            error = self._close(aclose())
            if error is not None:
                errors.append(error)
        if errors and exc is None:
            raise errors[0]

    def _close(self, closing: Coroutine[Any, Any, Any]) -> Exception | None:
        """Await a close coroutine, returning its failure instead of raising it.

        A stopped or closed bridge loop is logged and skipped. Any other close
        failure is logged and returned so the remaining resources still close.
        """
        try:
            run_sync(closing, timeout=_CLOSE_TIMEOUT)
        except (RuntimeError, TimeoutError) as error:
            with suppress(RuntimeError):
                closing.close()
            self._async.log(f"Resource close skipped: {error!r}")
        except Exception as error:
            self._async.log(f"Resource close failed: {error!r}")
            return error
        return None
