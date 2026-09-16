from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sci_etl_core.search.store_base import AsyncTextSearchStore, SearchDocument

if TYPE_CHECKING:
    from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, StoredRecord


@dataclass(frozen=True, slots=True)
class BackfillReport:
    """What :func:`backfill_text_index` did with each record of the vector memory.

    ``indexed`` records were written to the text index. ``skipped_existing``
    were already in it and left alone, and ``skipped_empty`` had no document to
    write, such as a record whose passages and title are all blank.
    """

    indexed: int = 0
    skipped_existing: int = 0
    skipped_empty: int = 0


def merge_passages(passages: Sequence[str], overlap_words: int) -> str:
    """Join overlapping passages back into one text, keeping each overlapping word once.

    Passages are split into words at whitespace, as
    :class:`~sci_etl_core.embeddings.chunking.SlidingWindowChunker` splits
    text, and the result joins the words with single spaces. Each passage after
    the first drops its first ``overlap_words`` words when they repeat the last
    words so far and it has more words than that, so the text of a
    sliding-window chunker comes back with every word counted once. Any other
    passage is kept whole, so passages from another chunker lose nothing.

    Raises:
        ValueError: ``overlap_words`` is negative.
    """
    if overlap_words < 0:
        raise ValueError("overlap_words must not be negative")
    words: list[str] = []
    for passage in passages:
        passage_words = passage.split()
        repeated = (
            0 < overlap_words < len(passage_words)
            and len(words) >= overlap_words
            and passage_words[:overlap_words] == words[-overlap_words:]
        )
        words.extend(passage_words[overlap_words:] if repeated else passage_words)
    return " ".join(words)


def stored_record_document(record: StoredRecord, body: str) -> SearchDocument | None:
    """Build the text-index document for a record read back from the vector memory.

    The title is the ``title`` of the record's chunk metadata, the body is
    ``body``, and the abstract is empty, because the vector memory does not
    hold it. The rest of the chunk metadata, such as ``source_url``, becomes the
    document's metadata; the record's original metadata, such as
    ``categories`` or ``year``, is not in the vector memory. A record with a
    blank title and a blank body gives ``None``.
    """
    title = record.metadata.get("title")
    title = title if isinstance(title, str) and title.strip() else ""
    body = body if body.strip() else ""
    if not (title or body):
        return None
    metadata = {key: value for key, value in record.metadata.items() if key != "title"}
    return SearchDocument(record.record_id, title=title, body=body, metadata=metadata)


async def backfill_text_index(
    vector_store: AsyncEmbeddingStore,
    text_store: AsyncTextSearchStore,
    *,
    overlap_words: int,
    replace_existing: bool = False,
    build_document: Callable[[StoredRecord, str], SearchDocument | None] = stored_record_document,
    batch_size: int = 100,
) -> BackfillReport:
    """Index the text already in the vector memory, so a deployment need not fetch full texts again.

    Every record of ``vector_store`` is read with
    :meth:`~sci_etl_core.embeddings.store_base.AsyncEmbeddingStore.iter_records`,
    its passages are joined by :func:`merge_passages` with ``overlap_words``,
    the overlap of the chunker that wrote them (for example
    ``SlidingWindowChunker().overlap_words``), and ``build_document`` turns the
    record and the joined text into the document to index. Joining without
    removing the overlap would count the words at every window boundary twice,
    and BM25 would over-weigh them.

    The default :func:`stored_record_document` has no abstract and none of the
    record's original metadata, so filters and facets on keys such as ``year``
    do not match a backfilled document. Pass a ``build_document`` that adds
    them from a source of your own, or return ``None`` to leave a record out.

    Records already in ``text_store`` are left alone unless
    ``replace_existing`` is true, because a document the pipeline indexed holds
    the abstract and metadata a backfilled one lacks. Documents are written
    ``batch_size`` at a time. Neither store is closed.

    Raises:
        ValueError: ``overlap_words`` is negative or ``batch_size`` is less than
            1, raised before any I/O.
        NotImplementedError: ``vector_store`` cannot enumerate its records.
        EmbeddingStoreError: The vector memory cannot be read.
        SearchStoreError: The text index cannot be read or written.
    """
    if overlap_words < 0:
        raise ValueError("overlap_words must not be negative")
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    existing: frozenset[str] = frozenset() if replace_existing else await text_store.filter_ids()
    indexed = skipped_existing = skipped_empty = 0
    pending: list[SearchDocument] = []
    async for record in vector_store.iter_records(batch_size):
        if record.record_id in existing:
            skipped_existing += 1
            continue
        document = build_document(record, merge_passages(record.passages, overlap_words))
        if document is None:
            skipped_empty += 1
            continue
        pending.append(document)
        if len(pending) >= batch_size:
            await text_store.index(pending)
            indexed += len(pending)
            pending = []
    if pending:
        await text_store.index(pending)
        indexed += len(pending)
    return BackfillReport(indexed, skipped_existing, skipped_empty)
