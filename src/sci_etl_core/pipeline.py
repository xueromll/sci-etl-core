from __future__ import annotations

from typing import Any

from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core._sync_bridge import run_sync


class ETLPipeline:
    """Synchronous facade for :class:`AsyncETLPipeline`.

    The only blocking entrypoint. All collaborators injected into the
    constructor must be async implementations.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._async = AsyncETLPipeline(*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> int:
        return run_sync(self._async.run(*args, **kwargs))

    def __enter__(self) -> ETLPipeline:
        return self

    def __exit__(self, *exc: Any) -> None:
        for resource in getattr(self._async, "_closeables", []):
            aclose = getattr(resource, "aclose", None)
            if aclose is not None:
                run_sync(aclose())