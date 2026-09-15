from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Collection, Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.exceptions import SearchStoreError
from sci_etl_core.search._schema import bootstrap, read_facet_keys, transaction, write_facet_keys
from sci_etl_core.search.compile_fts5 import to_filter_expression, to_match_expression
from sci_etl_core.search.filters import (
    SNIPPET_CLOSE,
    SNIPPET_ELLIPSIS,
    SNIPPET_OPEN,
    SNIPPET_TOKENS,
    MetadataFilter,
    encode_metadata,
    sanitize_text,
    split_markers,
    tag_rows,
    validate_facet_keys,
    validate_filters,
)
from sci_etl_core.search.query import Node
from sci_etl_core.search.store_base import AsyncTextSearchStore, BM25Weights, SearchDocument, TextHit

T = TypeVar("T")

_UPSERT = (
    "INSERT INTO documents (record_id, title, abstract, body, metadata, indexed_at) VALUES (?, ?, ?, ?, ?, ?)"
    " ON CONFLICT(record_id) DO UPDATE SET title = excluded.title, abstract = excluded.abstract,"
    " body = excluded.body, metadata = excluded.metadata, indexed_at = excluded.indexed_at"
)
_SELECT_DOC_ID = "SELECT doc_id FROM documents WHERE record_id = ?"
_DELETE_TAGS = "DELETE FROM document_tags WHERE doc_id = ?"
_INSERT_TAG = "INSERT INTO document_tags (doc_id, key, value) VALUES (?, ?, ?)"
_SEARCH = (
    "SELECT d.record_id, d.title, d.metadata, bm25(documents_fts, ?, ?, ?) AS score,"
    " snippet(documents_fts, -1, ?, ?, ?, ?)"
    " FROM documents_fts JOIN documents d ON d.doc_id = documents_fts.rowid"
    " WHERE documents_fts MATCH ?{conditions}"
    " ORDER BY score, d.record_id LIMIT ?"
)
_FACET_COUNTS = (
    "SELECT t.value, COUNT(*) AS matched FROM document_tags t JOIN documents d ON d.doc_id = t.doc_id"
    " WHERE t.key = ? AND {conditions} GROUP BY t.value ORDER BY matched DESC, t.value"
)
_ID_BATCH = 500


def fts5_available(connect: Callable[[], sqlite3.Connection] | None = None) -> bool:
    """Report whether this interpreter's SQLite was built with FTS5.

    ``connect`` opens the connection to probe, by default an in-memory database
    opened through :func:`sqlite3.connect` as it is at call time. A probe that
    cannot connect, or cannot create an FTS5 table, reports ``False``.
    """
    if connect is None:
        connect = _connect_in_memory
    try:
        connection = connect()
    except sqlite3.Error:
        return False
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(text)")
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return True


def _connect_in_memory() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AsyncSqliteFts5Store(AsyncTextSearchStore):
    """Durable lexical index on SQLite FTS5, keeping each article's text once.

    Backed by the standard-library ``sqlite3`` driver run off the event loop, so
    it carries no third-party dependency. The text lives in a ``documents``
    table and FTS5 holds only the inverted index, kept consistent by triggers.
    Every write is one transaction, so re-indexing a record replaces its text,
    metadata, and tags atomically. The single connection is used by one worker
    thread at a time, even when an awaiting task is cancelled, and every SQLite
    failure, including a file that is not a database, surfaces as
    :class:`~sci_etl_core.exceptions.SearchStoreError`.

    Ranking is FTS5's ``bm25()`` with the field ``weights``, reported as a
    score where higher is better. A snippet comes from the one field FTS5
    chooses. Each document's ``indexed_at`` is the UTC time from ``now``, as an
    ISO 8601 string with an offset.

    ``facet_keys`` names the metadata keys tagged for filters and facets. It is
    fixed for the life of the instance and recorded in the file. To change it,
    construct a store with the new keys and call :meth:`rebuild_tags`; until
    then a filter or facet on a key whose tags are not built raises
    :class:`~sci_etl_core.exceptions.SearchStoreError`.

    :meth:`aclose` is not terminal: a later call reopens the connection. Give
    each instance exactly one owner, which awaits :meth:`aclose`, and use it
    from one event loop. For a one-shot script, list the store in the
    pipeline's ``closeables``.

    Raises:
        SearchStoreError: This interpreter's SQLite was built without FTS5.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        facet_keys: Iterable[str] = (),
        weights: BM25Weights | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not fts5_available():
            raise SearchStoreError(
                "This Python's sqlite3 was built without FTS5, which AsyncSqliteFts5Store needs; "
                "use a Python whose SQLite includes FTS5, or InMemoryTextSearchStore"
            )
        self._path = str(path)
        self._facet_keys = frozenset(facet_keys)
        self._weights = BM25Weights() if weights is None else weights
        self._now = _utc_now if now is None else now
        self._runner = AsyncSqliteRunner(self._open_connection, error_factory=SearchStoreError)

    @property
    def facet_keys(self) -> frozenset[str]:
        return self._facet_keys

    async def index(self, documents: Sequence[SearchDocument]) -> None:
        if not documents:
            return
        rows = [self._row(document) for document in documents]
        await self._runner.run(lambda connection: self._write(connection, rows), "index search documents")

    async def delete_record(self, record_id: str) -> None:
        await self._runner.run(lambda connection: self._delete(connection, record_id), "delete a search document")

    async def replace_record(self, document: SearchDocument) -> None:
        """Replace the record's text, metadata, and tags in one transaction."""
        await self.index([document])

    async def search(
        self,
        query: Node,
        limit: int = 20,
        exclude_record_id: str | None = None,
        filters: Sequence[MetadataFilter] = (),
    ) -> list[TextHit]:
        validate_filters(filters, self._facet_keys)
        expression = to_match_expression(query)
        if limit < 1:
            return []
        conditions, condition_parameters = _conditions(None, filters)
        if exclude_record_id is not None:
            conditions.insert(0, "d.record_id != ?")
            condition_parameters.insert(0, exclude_record_id)
        sql = _SEARCH.format(conditions="".join(f" AND {condition}" for condition in conditions))
        parameters = [
            self._weights.title,
            self._weights.abstract,
            self._weights.body,
            SNIPPET_OPEN,
            SNIPPET_CLOSE,
            SNIPPET_ELLIPSIS,
            SNIPPET_TOKENS,
            expression,
            *condition_parameters,
            limit,
        ]
        rows = await self._read(filters, lambda connection: connection.execute(sql, parameters).fetchall())
        return [_hit(*row) for row in rows]

    async def filter_ids(
        self, query: Node | None = None, filters: Sequence[MetadataFilter] = ()
    ) -> frozenset[str]:
        validate_filters(filters, self._facet_keys)
        conditions, parameters = _conditions(None if query is None else to_filter_expression(query), filters)
        sql = f"SELECT d.record_id FROM documents d WHERE {' AND '.join(conditions) or '1'}"
        rows = await self._read(filters, lambda connection: connection.execute(sql, parameters).fetchall())
        return frozenset(record_id for (record_id,) in rows)

    async def get_documents(self, record_ids: Collection[str]) -> dict[str, SearchDocument]:
        wanted = sorted(set(record_ids))
        if not wanted:
            return {}
        rows = await self._runner.run(lambda connection: _select_documents(connection, wanted), "read search documents")
        return {
            record_id: SearchDocument(record_id, title, abstract, body, _decode_metadata(metadata))
            for record_id, title, abstract, body, metadata in rows
        }

    async def facet_counts(
        self,
        keys: Sequence[str],
        *,
        query: Node | None = None,
        filters: Sequence[MetadataFilter] = (),
    ) -> dict[str, tuple[tuple[str, int], ...]]:
        validate_filters(filters, self._facet_keys)
        validate_facet_keys(keys, self._facet_keys)
        filter_expression = None if query is None else to_filter_expression(query)
        statements: dict[str, tuple[str, list[Any]]] = {}
        for key in keys:
            others = [metadata_filter for metadata_filter in filters if metadata_filter.key != key]
            conditions, parameters = _conditions(filter_expression, others)
            sql = _FACET_COUNTS.format(conditions=" AND ".join(conditions) or "1")
            statements[key] = (sql, [key, *parameters])

        def count_values(connection: sqlite3.Connection) -> dict[str, tuple[tuple[str, int], ...]]:
            return {
                key: tuple((value, matched) for value, matched in connection.execute(sql, parameters).fetchall())
                for key, (sql, parameters) in statements.items()
            }

        return await self._read(filters, count_values, required_keys=keys)

    async def count(self) -> int:
        rows = await self._runner.run(
            lambda connection: connection.execute("SELECT COUNT(*) FROM documents").fetchall(),
            "count search documents",
        )
        return int(rows[0][0])

    async def optimize(self) -> None:
        """Merge the FTS5 index's segments, which speeds up later queries. Reads no text."""
        await self._runner.run(
            lambda connection: connection.execute("INSERT INTO documents_fts(documents_fts) VALUES ('optimize')"),
            "optimize the search index",
        )

    async def rebuild_index(self) -> None:
        """Re-tokenize every stored document into a fresh FTS5 index.

        The text already stored in the file is used; nothing is fetched again.
        This repairs an index that :meth:`integrity_check` reports inconsistent.
        """
        await self._runner.run(
            lambda connection: connection.execute("INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')"),
            "rebuild the search index",
        )

    async def rebuild_tags(self) -> None:
        """Re-derive every document's tags from its stored metadata, for this store's facet keys.

        One transaction replaces every tag and records :attr:`facet_keys` as
        built, so filters and facets on those keys work afterwards, and tags of
        keys no longer in :attr:`facet_keys` are gone. No text is read.

        Raises:
            SearchStoreError: The tags cannot be written, or a stored document's
                metadata is not a JSON object.
        """
        await self._runner.run(self._rebuild_tags, "rebuild search tags")

    async def integrity_check(self) -> bool:
        """Report whether the FTS5 index agrees with the stored documents.

        ``False`` means the index is inconsistent, for example after the
        ``documents`` table was written without its triggers;
        :meth:`rebuild_index` repairs it.

        Raises:
            SearchStoreError: The check could not run.
        """
        return await self._runner.run(_integrity_check, "check the search index")

    async def aclose(self) -> None:
        await self._runner.aclose()

    def _open_connection(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except sqlite3.Error as exc:
            raise SearchStoreError(f"Failed to open the SQLite search index: {exc}") from exc
        try:
            bootstrap(connection, self._facet_keys)
        except sqlite3.Error as exc:
            connection.close()
            raise SearchStoreError(f"Failed to open the SQLite search index: {exc}") from exc
        except SearchStoreError:
            connection.close()
            raise
        return connection

    def _row(self, document: SearchDocument) -> tuple[Any, ...]:
        encoded = encode_metadata(document.metadata)
        return (
            document.record_id,
            sanitize_text(document.title),
            sanitize_text(document.abstract),
            sanitize_text(document.body),
            encoded,
            self._now().isoformat(),
            tag_rows(json.loads(encoded), self._facet_keys),
        )

    async def _read(
        self,
        filters: Sequence[MetadataFilter],
        operation: Callable[[sqlite3.Connection], T],
        required_keys: Sequence[str] = (),
    ) -> T:
        keys = sorted({*required_keys, *(metadata_filter.key for metadata_filter in filters)})

        def read_consistently(connection: sqlite3.Connection) -> T:
            with transaction(connection, "DEFERRED"):
                if keys:
                    built = read_facet_keys(connection)
                    for key in keys:
                        if key not in built:
                            raise SearchStoreError(f"Tags for {key!r} are not built; call rebuild_tags()")
                return operation(connection)

        return await self._runner.run(read_consistently, "read the search index")

    @staticmethod
    def _write(connection: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
        with transaction(connection):
            for *document, tags in rows:
                connection.execute(_UPSERT, document)
                (doc_id,) = connection.execute(_SELECT_DOC_ID, (document[0],)).fetchone()
                connection.execute(_DELETE_TAGS, (doc_id,))
                connection.executemany(_INSERT_TAG, [(doc_id, key, value) for key, value in tags])

    @staticmethod
    def _delete(connection: sqlite3.Connection, record_id: str) -> None:
        with transaction(connection):
            connection.execute("DELETE FROM documents WHERE record_id = ?", (record_id,))

    def _rebuild_tags(self, connection: sqlite3.Connection) -> None:
        with transaction(connection):
            connection.execute("DELETE FROM document_tags")
            for doc_id, metadata in connection.execute("SELECT doc_id, metadata FROM documents").fetchall():
                tags = tag_rows(_decode_metadata(metadata), self._facet_keys)
                connection.executemany(_INSERT_TAG, [(doc_id, key, value) for key, value in tags])
            write_facet_keys(connection, self._facet_keys)


def _conditions(
    filter_expression: tuple[str, tuple[str, ...]] | None, filters: Iterable[MetadataFilter]
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    parameters: list[Any] = []
    if filter_expression is not None:
        conditions.append(filter_expression[0])
        parameters.extend(filter_expression[1])
    for metadata_filter in filters:
        placeholders = ", ".join("?" * len(metadata_filter.values))
        exists = "NOT EXISTS" if metadata_filter.negated else "EXISTS"
        conditions.append(
            f"{exists} (SELECT 1 FROM document_tags t WHERE t.doc_id = d.doc_id AND t.key = ?"
            f" AND t.value IN ({placeholders}))"
        )
        parameters.extend([metadata_filter.key, *sorted(metadata_filter.values)])
    return conditions, parameters


def _select_documents(connection: sqlite3.Connection, record_ids: list[str]) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for start in range(0, len(record_ids), _ID_BATCH):
        batch = record_ids[start : start + _ID_BATCH]
        placeholders = ", ".join("?" * len(batch))
        rows.extend(
            connection.execute(
                f"SELECT record_id, title, abstract, body, metadata FROM documents WHERE record_id IN ({placeholders})",
                batch,
            ).fetchall()
        )
    return rows


def _integrity_check(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("INSERT INTO documents_fts(documents_fts, rank) VALUES ('integrity-check', 1)")
    except sqlite3.OperationalError:
        raise
    except sqlite3.DatabaseError:
        return False
    return True


def _hit(record_id: str, title: str, metadata: str, rank: float, raw_snippet: str) -> TextHit:
    snippet, highlights = split_markers(raw_snippet)
    return TextHit(record_id, -rank, snippet, highlights, _decode_metadata(metadata), title)


def _decode_metadata(text: str) -> dict[str, Any]:
    try:
        metadata = json.loads(text)
    except ValueError:
        metadata = None
    if not isinstance(metadata, dict):
        raise SearchStoreError(f"A stored document's metadata is not a JSON object: {text[:80]!r}")
    return metadata
