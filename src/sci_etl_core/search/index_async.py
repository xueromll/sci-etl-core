from __future__ import annotations

from sci_etl_core.models import RawRecord
from sci_etl_core.search.store_base import AsyncTextSearchStore, SearchDocument


class AsyncSearchIndexer:
    """Index an article's title, abstract, and full text for Boolean search.

    The lexical counterpart of
    :class:`~sci_etl_core.embeddings.ingest_async.AsyncChunkIngestor`: the same
    ``ingest`` method and the same replace-not-append semantics, with one
    document per record instead of one row per chunk. It satisfies
    :class:`~sci_etl_core.ingest_protocol.MemoryIngestor`, so a search-only
    deployment passes it straight to the pipeline's ``memory_ingestor``.

    The indexer never swallows a failure and never parses a query; whether a
    store fault is fatal is decided by its caller. It borrows ``store`` and
    never closes it.
    """

    def __init__(self, store: AsyncTextSearchStore) -> None:
        self._store = store

    async def ingest(self, record: RawRecord, text: str) -> int:
        """Replace the record's indexed document with its title, abstract, and ``text``.

        A record whose title, abstract, and text are all blank (empty or
        whitespace only) is removed from the index, as ``AsyncChunkIngestor``
        clears a record whose text yields no passages. A record with any one of
        them non-blank is stored, with the blank fields stored as empty strings.
        ``record.metadata`` is copied into the document.

        Returns:
            1 when a document was stored, 0 when the record was cleared.

        Raises:
            SearchStoreError: The index could not be written.
        """
        title, abstract, body = _unless_blank(record.title), _unless_blank(record.abstract), _unless_blank(text)
        if not (title or abstract or body):
            await self._store.delete_record(record.record_id)
            return 0
        document = SearchDocument(record.record_id, title, abstract, body, dict(record.metadata))
        await self._store.replace_record(document)
        return 1


def _unless_blank(value: str) -> str:
    return value if value.strip() else ""
