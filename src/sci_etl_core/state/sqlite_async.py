from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Callable, TypeVar

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager

T = TypeVar("T")

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
    keeps the shared connection single-user.
    """

    def __init__(self, database_path: str | Path, timeout: float = 30.0) -> None:
        self._database_path = Path(database_path)
        self._timeout = timeout
        self._connection: sqlite3.Connection | None = None
        self._lock: asyncio.Lock | None = None

    async def load_processed_ids(self) -> set[str]:
        rows = await self._run(
            lambda connection: connection.execute("SELECT record_id FROM processed_ids").fetchall()
        )
        return {row[0] for row in rows}

    async def mark_processed(self, record_id: str) -> None:
        if not record_id:
            return
        await self._run(
            lambda connection: connection.execute(
                "INSERT OR IGNORE INTO processed_ids (record_id) VALUES (?)", (record_id,)
            )
        )

    async def load_metadata(self) -> PipelineMetadata:
        row = await self._run(
            lambda connection: connection.execute(
                "SELECT last_run_at, last_start_index FROM pipeline_metadata WHERE id = 1"
            ).fetchone()
        )
        if row is None:
            return PipelineMetadata()
        return PipelineMetadata(last_run_at=row[0], last_start_index=row[1])

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        await self._run(
            lambda connection: connection.execute(
                "INSERT INTO pipeline_metadata (id, last_run_at, last_start_index)"
                " VALUES (1, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET last_run_at = excluded.last_run_at,"
                " last_start_index = excluded.last_start_index",
                (metadata.last_run_at, metadata.last_start_index),
            )
        )

    async def flush(self) -> None:
        await self._run(lambda connection: connection.execute("PRAGMA wal_checkpoint(FULL)"))

    async def aclose(self) -> None:
        """Close the shared connection; a later call transparently reopens it."""
        async with self._get_lock():
            connection, self._connection = self._connection, None
        if connection is not None:
            await asyncio.to_thread(connection.close)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        async with self._get_lock():
            return await asyncio.to_thread(self._execute, operation)

    def _execute(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        return operation(self._connect())

    def _connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
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
        self._connection = connection
        return connection
