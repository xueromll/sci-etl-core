from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.search.filters import MetadataFilter, tag_rows, validate_facet_keys

if TYPE_CHECKING:
    from sci_etl_core.embeddings.async_base import AsyncEmbedder
    from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore
    from sci_etl_core.search.store_base import AsyncTextSearchStore, SearchDocument


class AsyncEdgeSource(ABC):
    """Finds each record's nearest records by one notion of relatedness, for a discovery graph.

    A source borrows the stores it reads and never closes them.
    """

    @property
    @abstractmethod
    def kind(self) -> str:
        """The kind of the edges this source produces, such as ``"semantic"``."""

    @abstractmethod
    async def neighbours(self, record_ids: Sequence[str], limit: int) -> dict[str, list[tuple[str, float]]]:
        """Return up to ``limit`` weighted neighbours for each record, best first.

        A neighbour is a ``(record_id, weight)`` pair, and a higher weight means
        more related. The ids arrive as one batch, one breadth-first level of a
        graph build, so a source can share work across them. Every requested
        record is a key of the result, mapping to an empty list when it has no
        neighbour.
        """


class MetadataEdgeSource(AsyncEdgeSource):
    """Relates records that share tag values, such as an arXiv category or an author.

    The weight is the Jaccard index of two records' tags under ``keys``: the
    ``(key, value)`` tags they share divided by all their distinct tags. It needs
    no embeddings, only tags built for ``keys`` in the text store (see
    :func:`~sci_etl_core.search.filters.tag_rows`).

    A batch costs one ``get_documents`` call for its records, one ``filter_ids``
    call per distinct ``(key, values)`` among them, and one ``get_documents``
    call for the candidates, so a tag shared by much of the corpus makes the
    candidate set large.

    Raises:
        ValueError: ``keys`` is empty, or a key is not one of the text store's
            facet keys.
    """

    def __init__(self, text_store: AsyncTextSearchStore, keys: Sequence[str] = ("categories", "authors")) -> None:
        if not keys:
            raise ValueError("MetadataEdgeSource needs at least one key")
        validate_facet_keys(keys, text_store.facet_keys)
        self._store = text_store
        self._keys = tuple(dict.fromkeys(keys))

    @property
    def kind(self) -> str:
        return "metadata"

    async def neighbours(self, record_ids: Sequence[str], limit: int) -> dict[str, list[tuple[str, float]]]:
        wanted = list(dict.fromkeys(record_ids))
        result: dict[str, list[tuple[str, float]]] = {record_id: [] for record_id in wanted}
        if limit < 1 or not wanted:
            return result
        tags = self._tags(await self._store.get_documents(wanted))
        record_filters = {
            record_id: [
                MetadataFilter(key, values)
                for key in self._keys
                if (values := frozenset(value for tag_key, value in record_tags if tag_key == key))
            ]
            for record_id, record_tags in tags.items()
        }
        matched: dict[MetadataFilter, frozenset[str]] = {}
        for filters in record_filters.values():
            for metadata_filter in filters:
                if metadata_filter not in matched:
                    matched[metadata_filter] = await self._store.filter_ids(None, [metadata_filter])
        candidates = {
            record_id: set[str]().union(*(matched[metadata_filter] for metadata_filter in filters)) - {record_id}
            for record_id, filters in record_filters.items()
        }
        other_tags = self._tags(await self._store.get_documents(set[str]().union(*candidates.values())))
        for record_id, others in candidates.items():
            scored = [(other, _jaccard(tags[record_id], other_tags[other])) for other in others if other in other_tags]
            result[record_id] = sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]
        return result

    def _tags(self, documents: dict[str, SearchDocument]) -> dict[str, frozenset[tuple[str, str]]]:
        return {
            record_id: frozenset(tag_rows(document.metadata, self._keys)) for record_id, document in documents.items()
        }


class EmbeddingEdgeSource(AsyncEdgeSource):
    """Relates records whose text means similar things, by cosine similarity in the vector memory.

    For each batch, the records' title and abstract are read from ``text_store``
    and embedded in one ``embed`` call. Each record then runs one vector-memory
    query for ``limit × chunk_pool_factor`` chunks, excluding its own chunks,
    and keeps each other record's best chunk, as
    :meth:`~sci_etl_core.embeddings.finder_async.AsyncSimilarArticleFinder.find_similar_articles`
    does. ``chunk_pool_factor`` has the meaning of
    :attr:`~sci_etl_core.search.hybrid_async.HybridParams.chunk_pool_factor`.
    A record absent from the text index, or whose title and abstract are both
    blank, has no neighbours. Only similarities of at least 0 count.

    The embedder and stores are used through ``embed`` and ``query`` only, so
    importing this module never loads NumPy. With an exact-scan vector store,
    every query scans every stored chunk.

    Raises:
        ValueError: ``chunk_pool_factor`` is less than 1.
    """

    def __init__(
        self,
        embedder: AsyncEmbedder,
        store: AsyncEmbeddingStore,
        text_store: AsyncTextSearchStore,
        *,
        chunk_pool_factor: int = 5,
    ) -> None:
        if chunk_pool_factor < 1:
            raise ValueError(f"chunk_pool_factor must be at least 1, not {chunk_pool_factor!r}")
        self._embedder = embedder
        self._store = store
        self._text_store = text_store
        self._chunk_pool_factor = chunk_pool_factor

    @property
    def kind(self) -> str:
        return "semantic"

    async def neighbours(self, record_ids: Sequence[str], limit: int) -> dict[str, list[tuple[str, float]]]:
        """Return each record's most similar records, best first.

        Raises:
            EmbeddingError: The embedder returned a different number of vectors
                than it was given texts.
        """
        wanted = list(dict.fromkeys(record_ids))
        result: dict[str, list[tuple[str, float]]] = {record_id: [] for record_id in wanted}
        if limit < 1 or not wanted:
            return result
        documents = await self._text_store.get_documents(wanted)
        texts = [
            (record_id, text)
            for record_id in wanted
            if record_id in documents and (text := _document_text(documents[record_id]))
        ]
        if not texts:
            return result
        vectors = await self._embedder.embed([text for _record_id, text in texts])
        if len(vectors) != len(texts):
            raise EmbeddingError(f"Embedder returned {len(vectors)} vectors for {len(texts)} texts")
        for (record_id, _text), vector in zip(texts, vectors, strict=True):
            hits = await self._store.query(vector, limit * self._chunk_pool_factor, 0.0, record_id)
            best: dict[str, float] = {}
            for hit in hits:
                best[hit.record_id] = max(best.get(hit.record_id, hit.score), hit.score)
            result[record_id] = sorted(best.items(), key=lambda item: (-item[1], item[0]))[:limit]
        return result


def _document_text(document: SearchDocument) -> str:
    return "\n\n".join(part for part in (document.title, document.abstract) if part.strip())


def _jaccard(first: frozenset[tuple[str, str]], second: frozenset[tuple[str, str]]) -> float:
    return len(first & second) / len(first | second)
