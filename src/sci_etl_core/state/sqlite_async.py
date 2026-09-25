from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sci_etl_core._migrations import Migration, migrate, newer_schema_message, transaction
from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.exceptions import StateStoreError
from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state._failures import bounded_error_text
from sci_etl_core.state.async_base import AsyncStateManager

_HEAD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("head_ids", "TEXT NOT NULL DEFAULT '[]'"),
    ("head_offset", "INTEGER NOT NULL DEFAULT 0"),
    ("tail_ids", "TEXT NOT NULL DEFAULT '[]'"),
)


def _add_head_columns(connection: sqlite3.Connection) -> None:
    existing = {row[1] for row in connection.execute("PRAGMA table_info(pipeline_metadata)")}
    for column, definition in _HEAD_COLUMNS:
        if column not in existing:
            connection.execute(f"ALTER TABLE pipeline_metadata ADD COLUMN {column} {definition}")


_MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        (
            "CREATE TABLE IF NOT EXISTS processed_ids (record_id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS pipeline_metadata ("
            " id INTEGER PRIMARY KEY CHECK (id = 1),"
            " last_run_at TEXT,"
            " last_start_index INTEGER NOT NULL DEFAULT 0)",
            _add_head_columns,
        ),
    ),
    (
        2,
        (
            "ALTER TABLE pipeline_metadata ADD COLUMN cursor TEXT",
            "ALTER TABLE pipeline_metadata ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0",
            "UPDATE pipeline_metadata SET cursor = CAST(last_start_index AS TEXT) WHERE last_start_index > 0",
            "CREATE TABLE record_failures ("
            " record_id TEXT PRIMARY KEY,"
            " attempts INTEGER NOT NULL,"
            " last_error TEXT NOT NULL)",
        ),
    ),
)


class AsyncSqliteStateManager(AsyncStateManager):
    """Transactional state backend built on the standard-library ``sqlite3``.

    Every mutation is an autocommitted statement or one short transaction,
    guarded by SQLite's own cross-process locking, so concurrent runs cannot
    interleave a half-written record. Blocking calls run in a worker thread and
    an :class:`asyncio.Lock` keeps the shared connection single-user, holding it
    until the thread finishes even if the awaiting task is cancelled.

    The database file and its parent folder are created on first use, and the
    file records its schema version in ``PRAGMA user_version``. A database
    written by sci-etl-core 0.4 is upgraded in place, its saved offset becoming
    the cursor. Failed attempts are stored per record with the last error,
    truncated to 4,096 characters, and :meth:`mark_processed` clears them.
    ``timeout`` is how many seconds a statement waits for another process's
    lock. A :class:`sqlite3.Error` propagates unwrapped, and a database written
    by a newer sci-etl-core raises
    :class:`~sci_etl_core.exceptions.StateStoreError`. Use each instance from
    one event loop.
    """

    def __init__(self, database_path: str | Path, timeout: float = 30.0) -> None:
        self._database_path = Path(database_path)
        self._timeout = timeout
        self._runner = AsyncSqliteRunner(self._open_connection, error_factory=None)

    async def load_processed_ids(self) -> set[str]:
        rows = await self._runner.run(
            lambda connection: connection.execute("SELECT record_id FROM processed_ids").fetchall(),
            "load processed ids",
        )
        return {row[0] for row in rows}

    async def mark_processed(self, record_id: str) -> None:
        """Record an id as processed and clear its failed attempts; an empty id is ignored."""
        if not record_id:
            return
        await self._runner.run(lambda connection: _mark(connection, record_id), "mark a record processed")

    async def record_failure(self, record_id: str, error: str) -> int:
        """Count a failed attempt and keep ``error``, truncated to 4,096 characters; an empty id is ignored."""
        if not record_id:
            return 0
        return await self._runner.run(
            lambda connection: _count_failure(connection, record_id, bounded_error_text(error)),
            "record a failed attempt",
        )

    async def failure_counts(self) -> dict[str, int]:
        rows = await self._runner.run(
            lambda connection: connection.execute("SELECT record_id, attempts FROM record_failures").fetchall(),
            "load failure counts",
        )
        return {record_id: attempts for record_id, attempts in rows}

    async def load_metadata(self) -> PipelineMetadata:
        row = await self._runner.run(
            lambda connection: connection.execute(
                "SELECT last_run_at, cursor, truncated, head_ids, head_offset, tail_ids"
                " FROM pipeline_metadata WHERE id = 1"
            ).fetchone(),
            "load pipeline metadata",
        )
        if row is None:
            return PipelineMetadata()
        return PipelineMetadata(
            last_run_at=row[0],
            cursor=row[1],
            truncated=bool(row[2]),
            head_ids=json.loads(row[3]),
            head_offset=row[4],
            tail_ids=json.loads(row[5]),
        )

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        await self._runner.run(
            lambda connection: connection.execute(
                "INSERT INTO pipeline_metadata (id, last_run_at, cursor, truncated, head_ids, head_offset, tail_ids)"
                " VALUES (1, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET last_run_at = excluded.last_run_at,"
                " cursor = excluded.cursor, truncated = excluded.truncated,"
                " head_ids = excluded.head_ids, head_offset = excluded.head_offset,"
                " tail_ids = excluded.tail_ids",
                (
                    metadata.last_run_at,
                    metadata.cursor,
                    int(metadata.truncated),
                    json.dumps(list(metadata.head_ids)),
                    metadata.head_offset,
                    json.dumps(list(metadata.tail_ids)),
                ),
            ),
            "save pipeline metadata",
        )

    async def flush(self) -> None:
        await self._runner.run(
            lambda connection: connection.execute("PRAGMA wal_checkpoint(FULL)"), "checkpoint the state database"
        )

    async def aclose(self) -> None:
        """Close the shared connection; a later call transparently reopens it."""
        await self._runner.aclose()

    def _open_connection(self) -> sqlite3.Connection:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self._database_path,
            timeout=self._timeout,
            check_same_thread=False,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            migrate(connection, _MIGRATIONS, _newer_schema_error)
        except BaseException:
            connection.close()
            raise
        return connection


def _mark(connection: sqlite3.Connection, record_id: str) -> None:
    with transaction(connection):
        connection.execute("INSERT OR IGNORE INTO processed_ids (record_id) VALUES (?)", (record_id,))
        connection.execute("DELETE FROM record_failures WHERE record_id = ?", (record_id,))


def _count_failure(connection: sqlite3.Connection, record_id: str, error: str) -> int:
    with transaction(connection):
        connection.execute(
            "INSERT INTO record_failures (record_id, attempts, last_error) VALUES (?, 1, ?)"
            " ON CONFLICT(record_id) DO UPDATE SET attempts = attempts + 1, last_error = excluded.last_error",
            (record_id, error),
        )
        row = connection.execute("SELECT attempts FROM record_failures WHERE record_id = ?", (record_id,)).fetchone()
    return int(row[0])


def _newer_schema_error(found: int, supported: int) -> StateStoreError:
    return StateStoreError(newer_schema_message("state database", found, supported))
