from __future__ import annotations

import sqlite3
from pathlib import Path

from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager

_SCHEMA: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS processed_ids (record_id TEXT PRIMARY KEY)",
    "CREATE TABLE IF NOT EXISTS pipeline_metadata ("
    " id INTEGER PRIMARY KEY CHECK (id = 1),"
    " last_run_at TEXT,"
    " last_start_index INTEGER NOT NULL DEFAULT 0)",
)


class AsyncSqliteStateManager(AsyncStateManager):
    """Transactional state backend built on the standard-library ``sqlite3``.

    Every mutation is an autocommitted statement guarded by SQLite's own
    cross-process locking, so concurrent runs cannot interleave a half-written
    record. Blocking calls run in a worker thread and an :class:`asyncio.Lock`
    keeps the shared connection single-user, holding it until the thread
    finishes even if the awaiting task is cancelled.

    The database file and its parent folder are created on first use.
    ``timeout`` is how many seconds a statement waits for another process's
    lock. A :class:`sqlite3.Error` propagates unwrapped. Use each instance from
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
        if not record_id:
            return
        await self._runner.run(
            lambda connection: connection.execute(
                "INSERT OR IGNORE INTO processed_ids (record_id) VALUES (?)", (record_id,)
            ),
            "mark a record processed",
        )

    async def load_metadata(self) -> PipelineMetadata:
        row = await self._runner.run(
            lambda connection: connection.execute(
                "SELECT last_run_at, last_start_index FROM pipeline_metadata WHERE id = 1"
            ).fetchone(),
            "load pipeline metadata",
        )
        if row is None:
            return PipelineMetadata()
        return PipelineMetadata(last_run_at=row[0], last_start_index=row[1])

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        await self._runner.run(
            lambda connection: connection.execute(
                "INSERT INTO pipeline_metadata (id, last_run_at, last_start_index)"
                " VALUES (1, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET last_run_at = excluded.last_run_at,"
                " last_start_index = excluded.last_start_index",
                (metadata.last_run_at, metadata.last_start_index),
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
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        for statement in _SCHEMA:
            connection.execute(statement)
        return connection
