from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from sci_etl_core._protocols import SupportsAclose, UsageReporter
from sci_etl_core._sync_bridge import bridge_loop, run_sync
from sci_etl_core.pipeline_async import AsyncETLPipeline

if TYPE_CHECKING:
    from sci_etl_core.config import PipelineConfig
    from sci_etl_core.exporters.async_base import AsyncExporter
    from sci_etl_core.extractors.async_base import AsyncExtractor
    from sci_etl_core.ingest_protocol import MemoryIngestor
    from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
    from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
    from sci_etl_core.observability import PipelineEvent, RunMetrics
    from sci_etl_core.signals import ShutdownSignal
    from sci_etl_core.state.async_base import AsyncStateManager

_CLOSE_TIMEOUT = 30.0


class ETLPipeline:
    """Synchronous facade for :class:`AsyncETLPipeline`.

    The only blocking entrypoint. It takes the arguments of
    :class:`AsyncETLPipeline`, and all collaborators injected into it must be
    async implementations. A full run is unbounded by default;
    ``run_timeout`` imposes a ceiling when the caller wants one.
    """

    def __init__(
        self,
        extractor: AsyncExtractor,
        relevance_filter: AsyncRelevanceFilter,
        entity_extractor: AsyncEntityExtractor,
        exporter: AsyncExporter,
        state_manager: AsyncStateManager,
        *,
        destination: str | None = None,
        max_concurrency: int = 6,
        logger: Callable[[str], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        closeables: Iterable[SupportsAclose] = (),
        memory_ingestor: MemoryIngestor | None = None,
        shutdown: ShutdownSignal | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
        usage_sources: Iterable[UsageReporter] = (),
        clock: Callable[[], float] = time.monotonic,
        run_timeout: float = math.inf,
    ) -> None:
        self._async = AsyncETLPipeline(
            extractor,
            relevance_filter,
            entity_extractor,
            exporter,
            state_manager,
            destination=destination,
            max_concurrency=max_concurrency,
            logger=logger,
            sleep=sleep,
            closeables=closeables,
            memory_ingestor=memory_ingestor,
            shutdown=shutdown,
            on_event=on_event,
            usage_sources=usage_sources,
            clock=clock,
        )
        self._run_timeout = run_timeout

    @classmethod
    def from_config(
        cls,
        pipeline: PipelineConfig,
        extractor: AsyncExtractor,
        relevance_filter: AsyncRelevanceFilter,
        entity_extractor: AsyncEntityExtractor,
        exporter: AsyncExporter,
        state_manager: AsyncStateManager,
        *,
        destination: str | None = None,
        max_concurrency: int | None = None,
        logger: Callable[[str], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        closeables: Iterable[SupportsAclose] = (),
        memory_ingestor: MemoryIngestor | None = None,
        shutdown: ShutdownSignal | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
        usage_sources: Iterable[UsageReporter] = (),
        clock: Callable[[], float] = time.monotonic,
        run_timeout: float = math.inf,
    ) -> ETLPipeline:
        """Build a pipeline configured as :meth:`AsyncETLPipeline.from_config` describes."""
        return cls(
            extractor,
            relevance_filter,
            entity_extractor,
            exporter,
            state_manager,
            destination=destination,
            max_concurrency=pipeline.max_concurrency if max_concurrency is None else max_concurrency,
            logger=logger,
            sleep=sleep,
            closeables=closeables,
            memory_ingestor=memory_ingestor,
            shutdown=shutdown,
            on_event=on_event,
            usage_sources=usage_sources,
            clock=clock,
            run_timeout=run_timeout,
        )

    def run(
        self,
        query: str,
        *,
        page_size: int = 100,
        sleep_between: float = 0.0,
        total_limit: int | None = None,
        start_index: int | None = None,
        newest_first: bool = False,
        max_attempts: int | None = 3,
    ) -> int:
        """Run :meth:`AsyncETLPipeline.run` with the same arguments and block until it ends.

        With a ``shutdown`` signal, its handlers are installed on the calling
        thread, which must be the main thread for signals to reach them, and
        set the flag on the background loop, so Ctrl+C stops the run as
        described for the async pipeline.
        """
        running = self._async.run(
            query,
            page_size=page_size,
            sleep_between=sleep_between,
            total_limit=total_limit,
            start_index=start_index,
            newest_first=newest_first,
            max_attempts=max_attempts,
        )
        shutdown = self._async.shutdown
        if shutdown is None:
            return run_sync(running, timeout=self._run_timeout)
        with shutdown.guard(loop=bridge_loop()):
            return run_sync(running, timeout=self._run_timeout)

    @property
    def last_run_metrics(self) -> RunMetrics | None:
        """Metrics of the most recent run, as :attr:`AsyncETLPipeline.last_run_metrics`."""
        return self._async.last_run_metrics

    def __enter__(self) -> ETLPipeline:
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
