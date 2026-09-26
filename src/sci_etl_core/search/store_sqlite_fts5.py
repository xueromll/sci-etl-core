from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Collection, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.exceptions import SearchQueryError, SearchStoreError
from sci_etl_core.search._schema import bootstrap, read_facet_keys, transaction, write_facet_keys
from sci_etl_core.search.compile_fts5 import to_filter_expression, to_match_expression
from sci_etl_core.search.filters import (
    SNIPPET_CLOSE,
    SNIPPET_ELLIPSIS,
    SNIPPET_OPEN,
    SNIPPET_TOKENS,
    RangeFilter,
    SearchFilter,
    encode_metadata,
    sanitize_text,
    split_markers,
    tag_in_range,
    tag_rows,
    validate_facet_keys,
    validate_filters,
)
from sci_etl_core.search.query import FIELDS, And, Near, Node, Not, Or, normalize
from sci_etl_core.search.store_base import AsyncTextSearchStore, BM25Weights, SearchDocument, Snippet, TextHit

T = TypeVar("T")

_UPSERT = (
    "INSERT INTO documents (record_id, title, abstract, body, metadata, indexed_at) VALUES (?, ?, ?, ?, ?, ?)"
    " ON CONFLICT(record_id) DO UPDATE SET title = excluded.title, abstract = excluded.abstract,"
    " body = excluded.body, metadata = excluded.metadata, indexed_at = excluded.indexed_at"
)
_SELECT_DOC_ID = "SELECT doc_id FROM documents WHERE record_id = ?"
_DELETE_TAGS = "DELETE FROM document_tags WHERE doc_id = ?"
_INSERT_TAG = "INSERT INTO document_tags (doc_id, key, value) VALUES (?, ?, ?)"
_SNIPPET = "snippet(documents_fts, {column}, ?, ?, ?, ?)"
_SEARCH = (
    "SELECT d.record_id, d.title, d.metadata, bm25(documents_fts, ?, ?, ?) AS score, "
    + ", ".join(_SNIPPET.format(column=column) for column in range(-1, len(FIELDS)))
    + " FROM documents_fts JOIN documents d ON d.doc_id = documents_fts.rowid"
    " WHERE documents_fts MATCH ?{conditions}"
    " ORDER BY score, d.record_id LIMIT ?"
)
_FACET_COUNTS = (
    "SELECT t.value, COUNT(*) AS matched FROM document_tags t JOIN documents d ON d.doc_id = t.doc_id"
    " WHERE t.key = ? AND {conditions} GROUP BY t.value ORDER BY matched DESC, t.value"
)
_RANGE_COUNT = "SELECT COUNT(*) FROM documents d WHERE {conditions}"
_MATCH_COUNT = "SELECT COUNT(*) FROM documents_fts WHERE documents_fts MATCH ?"
_ID_BATCH = 500
_IN_RANGE_FUNCTION = "sci_etl_tag_in_range"


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
    return datetime.now(UTC)


class AsyncSqliteFts5Store(AsyncTextSearchStore):
    """Durable lexical index on SQLite FTS5, keeping each article's text once.

    Backed by the standard-library ``sqlite3`` driver run off the event loop, so
    it carries no third-party dependency. The text lives in a ``documents``
    table and FTS5 holds only the inverted index, kept consistent by triggers.
    Every write is one transaction, so re-indexing a record replaces its text,
    metadata, and tags atomically. The single connection is used by one worker
    thread at a time, even when an awaiting task is cancelled, and every SQLite
    failure, including a file that is not a database, surfaces as
    :class:`~sci_etl_core.exceptions.SearchStoreError`. The one exception is a
    known SQLite fault: some builds, including 3.50.4, fail to highlight a
    field-scoped ``NEAR`` group inside ``OR`` for some documents and report
    the file as malformed. When the same match runs cleanly without
    highlighting, :meth:`search` raises
    :class:`~sci_etl_core.exceptions.SearchQueryError` naming the SQLite
    version instead.

    Ranking is FTS5's ``bm25()`` with the field ``weights``, reported as a
    score where higher is better. ``snippet`` comes from the one field FTS5
    chooses, and ``snippets`` holds FTS5's snippet of every field it
    highlights a match in. On the queries where FTS5 counts a word inside a
    part of the query that fails to match, as
    :class:`~sci_etl_core.search.store_memory.InMemoryTextSearchStore`
    describes, the two stores can highlight different words and so list
    different fields. Each document's ``indexed_at`` is the UTC time from
    ``now``, as an ISO 8601 string with an offset.

    ``facet_keys`` names the metadata keys tagged for filters and facets. It is
    fixed for the life of the instance and recorded in the file. To change it,
    construct a store with the new keys and call :meth:`rebuild_tags`; until
    then a filter or facet on a key whose tags are not built raises
    :class:`~sci_etl_core.exceptions.SearchStoreError`.

    The file is opened, and created or migrated to the current schema, on the
    first operation rather than at construction. A file that is not a database,
    or whose schema is newer than this library supports, raises
    :class:`~sci_etl_core.exceptions.SearchStoreError` then.

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
        filters: Sequence[SearchFilter] = (),
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
            *[SNIPPET_OPEN, SNIPPET_CLOSE, SNIPPET_ELLIPSIS, SNIPPET_TOKENS] * (len(FIELDS) + 1),
            expression,
            *condition_parameters,
            limit,
        ]
        try:
            rows = await self._read(filters, lambda connection: connection.execute(sql, parameters).fetchall())
        except SearchStoreError as error:
            if await self._is_snippet_fault(query, expression, error):
                raise SearchQueryError(
                    f"SQLite {sqlite3.sqlite_version} fails to highlight a field-scoped NEAR group inside OR "
                    "for some documents; drop the field scope from the NEAR group, or search each OR "
                    "alternative separately"
                ) from error
            raise
        return [_hit(*row) for row in rows]

    async def filter_ids(
        self, query: Node | None = None, filters: Sequence[SearchFilter] = ()
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
        filters: Sequence[SearchFilter] = (),
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

    async def range_counts(
        self,
        ranges: Sequence[RangeFilter],
        *,
        query: Node | None = None,
        filters: Sequence[SearchFilter] = (),
    ) -> tuple[int, ...]:
        """Count matching documents inside each of ``ranges`` in one consistent read.

        The counts are those :meth:`AsyncTextSearchStore.range_counts` describes.
        """
        validate_filters(filters, self._facet_keys)
        range_keys = [search_range.key for search_range in ranges]
        validate_facet_keys(range_keys, self._facet_keys)
        filter_expression = None if query is None else to_filter_expression(query)
        statements: list[tuple[str, list[Any]]] = []
        for search_range in ranges:
            others = [search_filter for search_filter in filters if search_filter.key != search_range.key]
            conditions, parameters = _conditions(filter_expression, [*others, search_range])
            statements.append((_RANGE_COUNT.format(conditions=" AND ".join(conditions)), parameters))

        def count_ranges(connection: sqlite3.Connection) -> tuple[int, ...]:
            return tuple(int(connection.execute(sql, parameters).fetchone()[0]) for sql, parameters in statements)

        return await self._read(filters, count_ranges, required_keys=range_keys)

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
        """Close the connection; a later call transparently reopens it."""
        await self._runner.aclose()

    def _open_connection(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except sqlite3.Error as exc:
            raise SearchStoreError(f"Failed to open the SQLite search index: {exc}") from exc
        try:
            connection.create_function(_IN_RANGE_FUNCTION, 3, tag_in_range, deterministic=True)
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

    async def _is_snippet_fault(self, query: Node, expression: str, error: SearchStoreError) -> bool:
        cause = error.__cause__
        if not (
            isinstance(cause, sqlite3.DatabaseError)
            and "malformed" in str(cause)
            and _scoped_near_inside_or(normalize(query))
        ):
            return False
        try:
            await self._read((), lambda connection: connection.execute(_MATCH_COUNT, (expression,)).fetchone())
        except SearchStoreError:
            return False
        return True

    async def _read(
        self,
        filters: Sequence[SearchFilter],
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
    filter_expression: tuple[str, tuple[str, ...]] | None, filters: Iterable[SearchFilter]
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    parameters: list[Any] = []
    if filter_expression is not None:
        conditions.append(filter_expression[0])
        parameters.extend(filter_expression[1])
    for search_filter in filters:
        exists = "NOT EXISTS" if search_filter.negated else "EXISTS"
        if isinstance(search_filter, RangeFilter):
            test = f"{_IN_RANGE_FUNCTION}(t.value, ?, ?)"
            values: list[Any] = [search_filter.low, search_filter.high]
        else:
            test = f"t.value IN ({', '.join('?' * len(search_filter.values))})"
            values = sorted(search_filter.values)
        conditions.append(
            f"{exists} (SELECT 1 FROM document_tags t WHERE t.doc_id = d.doc_id AND t.key = ? AND {test})"
        )
        parameters.extend([search_filter.key, *values])
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


def _scoped_near_inside_or(node: Node, inside_or: bool = False) -> bool:
    if isinstance(node, Near):
        return inside_or and bool(node.fields)
    if isinstance(node, Not):
        return _scoped_near_inside_or(node.operand, inside_or)
    if isinstance(node, (And, Or)):
        nested = inside_or or isinstance(node, Or)
        return any(_scoped_near_inside_or(operand, nested) for operand in node.operands)
    return False


def _hit(record_id: str, title: str, metadata: str, rank: float, raw_snippet: str, *raw_fields: str) -> TextHit:
    snippet, highlights = split_markers(raw_snippet)
    snippets = tuple(
        Snippet(name, *marked)
        for name, raw_field in zip(FIELDS, raw_fields, strict=True)
        if (marked := split_markers(raw_field))[1]
    )
    return TextHit(record_id, -rank, snippet, highlights, _decode_metadata(metadata), title, snippets)


def _decode_metadata(text: str) -> dict[str, Any]:
    try:
        metadata = json.loads(text)
    except ValueError:
        metadata = None
    if not isinstance(metadata, dict):
        raise SearchStoreError(f"A stored document's metadata is not a JSON object: {text[:80]!r}")
    return metadata
