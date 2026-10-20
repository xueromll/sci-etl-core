from __future__ import annotations

from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import RawRecord


class AsyncCascadingRelevanceFilter(AsyncRelevanceFilter):
    """Run relevance filters in order and stop at the first rejection.

    A record is relevant only when every filter accepts it. The filters run one
    at a time, in the order given, and the first one that rejects a record ends
    the cascade, so the filters after it never see that record. Put a cheap
    filter, such as
    :class:`~sci_etl_core.llm.relevance_embedding_async.AsyncEmbeddingRelevanceFilter`,
    before an expensive one, such as
    :class:`~sci_etl_core.llm.relevance_async.AsyncLLMRelevanceFilter`, so the
    expensive filter is asked only about the records the cheap one kept.

    An exception from a filter, :class:`asyncio.CancelledError` included,
    propagates unchanged, and the filters after it are not called. The cascade
    never reads a fault as a rejection, since a rejection marks the record
    processed for good: each filter's own ``default_on_error`` decides whether
    its faults let the record through or raise. The cascade borrows its filters
    and never closes anything. Token usage is reported by the clients the
    filters use, which belong in the pipeline's ``usage_sources``.
    """

    def __init__(self, *filters: AsyncRelevanceFilter) -> None:
        """Combine ``filters``, which then run in the order given.

        Raises:
            ValueError: ``filters`` is empty.
        """
        if not filters:
            raise ValueError("AsyncCascadingRelevanceFilter needs at least one filter")
        self._filters = filters

    async def is_relevant(self, record: RawRecord) -> bool:
        """Return ``True`` when every filter accepts ``record``, stopping at the first rejection.

        Raises:
            SciEtlError: A filter raised it, such as the ``LLMError`` or
                ``EmbeddingError`` of a bundled filter built with
                ``default_on_error=False``. It propagates unchanged, and the
                filters after it are not called.
        """
        for relevance_filter in self._filters:
            if not await relevance_filter.is_relevant(record):
                return False
        return True
