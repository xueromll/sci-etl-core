from __future__ import annotations

import asyncio
from collections.abc import Callable

from sci_etl_core.ingest_protocol import MEMORY_FAULTS, MemoryIngestor
from sci_etl_core.models import RawRecord
from sci_etl_core.search.index_async import AsyncSearchIndexer


class AsyncCompositeIngestor:
    """Send one record's text to several memory backends concurrently.

    A memory fault (:data:`~sci_etl_core.ingest_protocol.MEMORY_FAULTS`) in one
    backend is logged and does not stop the others, so a broken text index
    never costs a record its embeddings, and never costs it its entity export.
    Any other exception is re-raised after every backend has finished, the
    first in ingestor order when several fail. Cancelling the awaiting task
    cancels every backend.

    Log lines read ``Memory ingest failed for <record_id> in <IngestorClass>:
    <error>``. Pass the pipeline's own logger, so memory faults share one
    stream. The composite borrows its ingestors and never closes anything.
    """

    def __init__(self, *ingestors: MemoryIngestor, logger: Callable[[str], None] | None = None) -> None:
        """Combine ``ingestors``, which then run concurrently on every record.

        ``ingest`` returns the first ingestor's count, so the first ingestor
        must not be an ``AsyncSearchIndexer``; pass the chunk ingestor first.
        The pipeline ignores the return value.

        Raises:
            ValueError: ``ingestors`` is empty, or its first element is an
                ``AsyncSearchIndexer``.
        """
        if not ingestors:
            raise ValueError("AsyncCompositeIngestor needs at least one ingestor")
        if isinstance(ingestors[0], AsyncSearchIndexer):
            raise ValueError(
                "The first ingestor's count is returned, so it must not be an AsyncSearchIndexer; "
                "pass the chunk ingestor first"
            )
        self._ingestors = ingestors
        self._log = logger or (lambda _msg: None)

    async def ingest(self, record: RawRecord, text: str) -> int:
        """Return the first ingestor's count, or 0 if its memory fault was absorbed."""
        results = await asyncio.gather(
            *(self._guarded(ingestor, record, text) for ingestor in self._ingestors), return_exceptions=True
        )
        counts: list[int] = []
        for result in results:
            if isinstance(result, BaseException):
                raise result
            counts.append(result)
        return counts[0]

    async def _guarded(self, ingestor: MemoryIngestor, record: RawRecord, text: str) -> int:
        try:
            return await ingestor.ingest(record, text)
        except MEMORY_FAULTS as exc:
            self._log(f"Memory ingest failed for {record.record_id} in {type(ingestor).__name__}: {exc!r}")
            return 0
