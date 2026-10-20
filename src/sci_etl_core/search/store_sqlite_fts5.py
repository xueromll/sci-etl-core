from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.exceptions import SearchQueryError, SearchStoreError
from sci_etl_core.search._schema import bootstrap, read_facet_keys, transaction, write_facet_keys
from sci_etl_core.search.compile_fts5 import is_rankable, to_filter_expression, to_match_expression
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
_SNIPPET_PARAMETERS = [SNIPPET_OPEN, SNIPPET_CLOSE, SNIPPET_ELLIPSIS, SNIPPET_TOKENS] * (len(FIELDS) + 1)
_RANK = (
    "SELECT documents_fts.rowid, bm25(documents_fts, ?, ?, ?) AS score FROM documents_fts"
    " WHERE documents_fts MATCH ?{conditions} ORDER BY score LIMIT ?"
)
_RANK_BY_RECORD = (
    "SELECT documents_fts.rowid, d.record_id, bm25(documents_fts, ?, ?, ?) AS score"
    " FROM documents_fts JOIN documents d ON d.doc_id = documents_fts.rowid"
    " WHERE documents_fts MATCH ?{conditions} ORDER BY score, d.record_id LIMIT ?"
)
_HIGHLIGHT = (
    "SELECT documents_fts.rowid, d.title, d.metadata, "
    + ", ".join(_SNIPPET.format(column=column) for column in range(-1, len(FIELDS)))
    + " FROM documents_fts JOIN documents d ON d.doc_id = documents_fts.rowid"
    " WHERE documents_fts MATCH ? AND +documents_fts.rowid IN ({placeholders})"
)
_EXCLUDE_DOC_ID = "documents_fts.rowid IS NOT (SELECT doc_id FROM documents WHERE record_id = ?)"
_FACET_COUNTS = (
    "SELECT t.value, COUNT(*) AS matched FROM document_tags t JOIN documents d ON d.doc_id = t.doc_id"
    " WHERE t.key = ? AND {conditions} GROUP BY t.value ORDER BY matched DESC, t.value"
)
_TAG_COUNTS = (
    "SELECT f.value, COUNT(*) AS matched FROM document_tags f"
    " WHERE f.key = ?{conditions} GROUP BY f.value ORDER BY matched DESC, f.value"
)
_MATCHED_TAG_COUNTS = (
    "SELECT f.value, COUNT(*) AS matched FROM documents_fts"
    " CROSS JOIN document_tags f ON f.doc_id = documents_fts.rowid AND f.key = ?"
    " WHERE documents_fts MATCH ?{conditions} GROUP BY f.value ORDER BY matched DESC, f.value"
)
_RANGE_COUNT = "SELECT COUNT(*) FROM documents d WHERE {conditions}"
_MATCH_COUNT = "SELECT COUNT(*) FROM documents_fts WHERE documents_fts MATCH ?"
_COUNT_MATCHED = "SELECT COUNT(*) FROM (SELECT 1 FROM documents_fts WHERE documents_fts MATCH ?{conditions} LIMIT ?)"
_COUNT_DOCUMENTS = "SELECT COUNT(*) FROM (SELECT 1 FROM documents d WHERE {conditions} LIMIT ?)"
_ID_BATCH = 500
_IN_RANGE_FUNCTION = "sci_etl_tag_in_range"
_FTS_DOC_ID = "documents_fts.rowid"
_SQLITE_MAX_INTEGER = 2**63 - 1
_DOCUMENT_COLUMNS = "record_id, title, abstract, body, metadata"
_HEADER_COLUMNS = "record_id, title, metadata"
_Ranked = list[tuple[int, str, float]]


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteTuning:
    """Memory settings for the SQLite connection of one store.

    ``cache_size`` is SQLite's page cache in bytes, rounded down to whole
    kibibytes, and ``mmap_size`` the most bytes of the file SQLite reads through
    a memory map. ``None`` keeps SQLite's default, a page cache of about 2 MB
    and no memory map, so ``SqliteTuning()`` changes nothing. A larger cache and
    a memory map speed up queries once the index outgrows the default cache, at
    the cost of the process's memory, which is why both are opt-in.

    Raises:
        ValueError: A size is not a whole number of bytes, or is negative.
    """

    cache_size: int | None = None
    mmap_size: int | None = None

    def __post_init__(self) -> None:
        for name in ("cache_size", "mmap_size"):
            size = getattr(self, name)
            if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
                raise ValueError(f"{name} must be a whole number of bytes that is not negative, not {size!r}")


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
    field-scoped ``NEAR`` group inside ``OR`` or ``NOT`` for some documents and report
    the file as malformed. When the same match runs cleanly without
    highlighting, :meth:`search`, :meth:`rank`, and :meth:`hydrate` raise
    :class:`~sci_etl_core.exceptions.SearchQueryError` naming the SQLite
    version instead.

    Ranking is FTS5's ``bm25()`` with the field ``weights``, reported as a
    score where higher is better. A search ranks the matches first and
    computes snippets, and reads titles and metadata, only for the hits it
    returns, so its cost follows ``limit`` rather than the number of matches.
    ``snippet`` comes from the one field FTS5
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
    :class:`~sci_etl_core.exceptions.SearchStoreError` then. ``tuning`` sets
    the connection's page cache and memory map (:class:`SqliteTuning`); by
    default SQLite's own settings apply.

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
        tuning: SqliteTuning | None = None,
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
        self._tuning = SqliteTuning() if tuning is None else tuning
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
        rank = self._ranking(expression, limit, exclude_record_id, filters)

        def rank_and_highlight(connection: sqlite3.Connection) -> list[TextHit]:
            ranked = rank(connection)
            found = _highlights(connection, expression, [rowid for rowid, _record_id, _rank in ranked])
            return [_hit(record_id, rank, *found[rowid]) for rowid, record_id, rank in ranked]

        return await self._highlighting(query, expression, filters, rank_and_highlight)

    async def rank(
        self,
        query: Node,
        limit: int = 20,
        exclude_record_id: str | None = None,
        filters: Sequence[SearchFilter] = (),
    ) -> list[TextHit]:
        """Return :meth:`search`'s hits with their record ids and scores only.

        No snippet is computed and no title or metadata is read, so ranking a
        pool of 500 costs little more than ranking 20. :meth:`hydrate` completes
        the hits a caller shows.
        """
        validate_filters(filters, self._facet_keys)
        expression = to_match_expression(query)
        if limit < 1:
            return []
        ranked = await self._highlighting(
            query, expression, filters, self._ranking(expression, limit, exclude_record_id, filters)
        )
        return [TextHit(record_id, -rank) for _rowid, record_id, rank in ranked]

    async def hydrate(self, query: Node, hits: Sequence[TextHit]) -> list[TextHit]:
        """Compute the snippets, and read the title and metadata, of ``hits`` in one consistent read.

        The snippets are the ones :meth:`search` computes, as
        :meth:`AsyncTextSearchStore.hydrate` describes.
        """
        expression = to_match_expression(query)
        if not hits:
            return []
        wanted = sorted({hit.record_id for hit in hits})

        def highlight(connection: sqlite3.Connection) -> dict[str, tuple[Any, ...]]:
            doc_ids = dict(_select_documents(connection, wanted, "record_id, doc_id"))
            found = _highlights(connection, expression, sorted(doc_ids.values()))
            return {record_id: found[doc_id] for record_id, doc_id in doc_ids.items() if doc_id in found}

        rows = await self._highlighting(query, expression, (), highlight)
        hydrated: list[TextHit] = []
        for hit in hits:
            row = rows.get(hit.record_id)
            hydrated.append(hit if row is None else _hit(hit.record_id, -hit.score, *row))
        return hydrated

    async def filter_ids(
        self, query: Node | None = None, filters: Sequence[SearchFilter] = ()
    ) -> frozenset[str]:
        validate_filters(filters, self._facet_keys)
        conditions, parameters = _conditions(None if query is None else to_filter_expression(query), filters)
        sql = f"SELECT d.record_id FROM documents d WHERE {' AND '.join(conditions) or '1'}"
        rows = await self._read(filters, lambda connection: connection.execute(sql, parameters).fetchall())
        return frozenset(record_id for (record_id,) in rows)

    async def filter_candidates(
        self, record_ids: Collection[str], filters: Sequence[SearchFilter] = ()
    ) -> frozenset[str]:
        """Test ``filters`` on ``record_ids`` alone, 500 ids per statement, in one consistent read."""
        validate_filters(filters, self._facet_keys)
        wanted = sorted(set(record_ids))
        conditions, parameters = _conditions(None, filters)
        restriction = _restriction(conditions)

        def select(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
            rows: list[tuple[Any, ...]] = []
            for start in range(0, len(wanted), _ID_BATCH):
                batch = wanted[start : start + _ID_BATCH]
                placeholders = ", ".join("?" * len(batch))
                sql = f"SELECT d.record_id FROM documents d WHERE d.record_id IN ({placeholders}){restriction}"
                rows.extend(connection.execute(sql, [*batch, *parameters]).fetchall())
            return rows

        rows = await self._read(filters, select)
        return frozenset(record_id for (record_id,) in rows)

    async def get_documents(self, record_ids: Collection[str]) -> dict[str, SearchDocument]:
        wanted = sorted(set(record_ids))
        if not wanted:
            return {}
        rows = await self._runner.run(
            lambda connection: _select_documents(connection, wanted, _DOCUMENT_COLUMNS), "read search documents"
        )
        return {
            record_id: SearchDocument(record_id, title, abstract, body, _decode_metadata(metadata))
            for record_id, title, abstract, body, metadata in rows
        }

    async def get_headers(self, record_ids: Collection[str]) -> dict[str, SearchDocument]:
        """Read the title and metadata of each record, never selecting its abstract or body."""
        wanted = sorted(set(record_ids))
        if not wanted:
            return {}
        rows = await self._runner.run(
            lambda connection: _select_documents(connection, wanted, _HEADER_COLUMNS), "read search documents"
        )
        return {
            record_id: SearchDocument(record_id, title, metadata=_decode_metadata(metadata))
            for record_id, title, metadata in rows
        }

    async def facet_counts(
        self,
        keys: Sequence[str],
        *,
        query: Node | None = None,
        filters: Sequence[SearchFilter] = (),
    ) -> dict[str, tuple[tuple[str, int], ...]]:
        """Count matching documents per value of each facet key, in one consistent read.

        The counts are those :meth:`AsyncTextSearchStore.facet_counts`
        describes. For a rankable query the counts are driven by the query's
        matches, joined to their tags, and with no query by the tag index alone,
        so neither reads every tag of a key against the documents table.
        """
        validate_filters(filters, self._facet_keys)
        validate_facet_keys(keys, self._facet_keys)
        match = None if query is None or not is_rankable(query) else to_match_expression(query)
        filter_expression = None if query is None or match is not None else to_filter_expression(query)
        statements: dict[str, tuple[str, list[Any]]] = {}
        for key in keys:
            others = [metadata_filter for metadata_filter in filters if metadata_filter.key != key]
            if match is not None:
                conditions, parameters = _conditions(None, others, _FTS_DOC_ID)
                sql = _MATCHED_TAG_COUNTS.format(conditions=_restriction(conditions))
                statements[key] = (sql, [key, match, *parameters])
            elif filter_expression is None:
                conditions, parameters = _conditions(None, others, "f.doc_id")
                statements[key] = (_TAG_COUNTS.format(conditions=_restriction(conditions)), [key, *parameters])
            else:
                conditions, parameters = _conditions(filter_expression, others)
                statements[key] = (_FACET_COUNTS.format(conditions=" AND ".join(conditions)), [key, *parameters])

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

    async def count_matches(
        self,
        query: Node | None = None,
        filters: Sequence[SearchFilter] = (),
        *,
        cap: int | None = None,
    ) -> int:
        """Count matching documents with ``COUNT(*)``, never returning their ids.

        The count is the one :meth:`AsyncTextSearchStore.count_matches`
        describes. A rankable query is counted on its FTS5 matches alone, and
        ``cap`` stops the count after ``cap`` documents, so a capped count of a
        frequent word costs ``cap`` steps rather than one per match.
        """
        validate_filters(filters, self._facet_keys)
        if cap is not None and cap < 1:
            raise ValueError(f"cap must be at least 1, not {cap!r}")
        limit = -1 if cap is None else cap
        if query is not None and is_rankable(query):
            conditions, parameters = _conditions(None, filters, _FTS_DOC_ID)
            sql = _COUNT_MATCHED.format(conditions=_restriction(conditions))
            parameters = [to_match_expression(query), *parameters, limit]
        else:
            conditions, parameters = _conditions(None if query is None else to_filter_expression(query), filters)
            sql = _COUNT_DOCUMENTS.format(conditions=" AND ".join(conditions) or "1")
            parameters.append(limit)
        row = await self._read(filters, lambda connection: connection.execute(sql, parameters).fetchone())
        return int(row[0])

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
            _tune(connection, self._tuning)
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

    def _ranking(
        self, expression: str, limit: int, exclude_record_id: str | None, filters: Sequence[SearchFilter]
    ) -> Callable[[sqlite3.Connection], _Ranked]:
        weights = [self._weights.title, self._weights.abstract, self._weights.body]
        conditions, parameters = _conditions(None, filters, _FTS_DOC_ID)
        joined_conditions, joined_parameters = _conditions(None, filters)
        if exclude_record_id is not None:
            conditions.insert(0, _EXCLUDE_DOC_ID)
            parameters.insert(0, exclude_record_id)
            joined_conditions.insert(0, "d.record_id != ?")
            joined_parameters.insert(0, exclude_record_id)
        fetched = limit + 1 if limit < _SQLITE_MAX_INTEGER else limit
        by_score = (_RANK.format(conditions=_restriction(conditions)), [*weights, expression, *parameters, fetched])
        by_record = (
            _RANK_BY_RECORD.format(conditions=_restriction(joined_conditions)),
            [*weights, expression, *joined_parameters, limit],
        )

        def rank(connection: sqlite3.Connection) -> _Ranked:
            scored: list[tuple[int, float]] = connection.execute(*by_score).fetchall()
            if len(scored) > limit and scored[limit - 1][1] == scored[limit][1]:
                return connection.execute(*by_record).fetchall()
            top = scored[:limit]
            names = _record_ids(connection, [rowid for rowid, _rank in top])
            if len(names) < len(top):
                return connection.execute(*by_record).fetchall()
            return sorted(((rowid, names[rowid], rank) for rowid, rank in top), key=lambda row: (row[2], row[1]))

        return rank

    async def _highlighting(
        self,
        query: Node,
        expression: str,
        filters: Sequence[SearchFilter],
        operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        try:
            return await self._read(filters, operation)
        except SearchStoreError as error:
            if await self._is_snippet_fault(query, expression, error):
                raise SearchQueryError(
                    f"SQLite {sqlite3.sqlite_version} fails to highlight a field-scoped NEAR group inside OR "
                    "or NOT for some documents; drop the field scope from the NEAR group"
                ) from error
            raise

    async def _is_snippet_fault(self, query: Node, expression: str, error: SearchStoreError) -> bool:
        cause = error.__cause__
        if not (
            isinstance(cause, sqlite3.DatabaseError)
            and "malformed" in str(cause)
            and _optional_scoped_near(normalize(query))
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


def _tune(connection: sqlite3.Connection, tuning: SqliteTuning) -> None:
    if tuning.cache_size is not None:
        connection.execute(f"PRAGMA cache_size = {-(tuning.cache_size // 1024)}")
    if tuning.mmap_size is not None:
        connection.execute(f"PRAGMA mmap_size = {tuning.mmap_size}")


def _restriction(conditions: Iterable[str]) -> str:
    return "".join(f" AND {condition}" for condition in conditions)


def _conditions(
    filter_expression: tuple[str, tuple[str, ...]] | None, filters: Iterable[SearchFilter], doc_id: str = "d.doc_id"
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
            f"{exists} (SELECT 1 FROM document_tags t WHERE t.doc_id = {doc_id} AND t.key = ? AND {test})"
        )
        parameters.extend([search_filter.key, *values])
    return conditions, parameters


def _select_documents(connection: sqlite3.Connection, record_ids: list[str], columns: str) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for start in range(0, len(record_ids), _ID_BATCH):
        batch = record_ids[start : start + _ID_BATCH]
        placeholders = ", ".join("?" * len(batch))
        rows.extend(
            connection.execute(
                f"SELECT {columns} FROM documents WHERE record_id IN ({placeholders})",
                batch,
            ).fetchall()
        )
    return rows


def _record_ids(connection: sqlite3.Connection, doc_ids: list[int]) -> dict[int, str]:
    names: dict[int, str] = {}
    for start in range(0, len(doc_ids), _ID_BATCH):
        batch = doc_ids[start : start + _ID_BATCH]
        placeholders = ", ".join("?" * len(batch))
        names.update(
            connection.execute(f"SELECT doc_id, record_id FROM documents WHERE doc_id IN ({placeholders})", batch)
        )
    return names


def _highlights(connection: sqlite3.Connection, expression: str, doc_ids: list[int]) -> dict[int, tuple[Any, ...]]:
    found: dict[int, tuple[Any, ...]] = {}
    for start in range(0, len(doc_ids), _ID_BATCH):
        batch = doc_ids[start : start + _ID_BATCH]
        sql = _HIGHLIGHT.format(placeholders=", ".join("?" * len(batch)))
        for doc_id, *row in connection.execute(sql, [*_SNIPPET_PARAMETERS, expression, *batch]):
            found[doc_id] = tuple(row)
    return found


def _integrity_check(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("INSERT INTO documents_fts(documents_fts, rank) VALUES ('integrity-check', 1)")
    except sqlite3.OperationalError:
        raise
    except sqlite3.DatabaseError:
        return False
    return True


def _optional_scoped_near(node: Node, optional: bool = False) -> bool:
    if isinstance(node, Near):
        return optional and bool(node.fields)
    if isinstance(node, Not):
        return _optional_scoped_near(node.operand, True)
    if isinstance(node, (And, Or)):
        nested = optional or isinstance(node, Or)
        return any(_optional_scoped_near(operand, nested) for operand in node.operands)
    return False


def _hit(record_id: str, rank: float, title: str, metadata: str, raw_snippet: str, *raw_fields: str) -> TextHit:
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
