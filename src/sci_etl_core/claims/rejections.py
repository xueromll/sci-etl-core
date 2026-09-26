from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci_etl_core._migrations import Migration, migrate, newer_schema_message, transaction
from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.claims.models import ExtractionStamp, content_hash
from sci_etl_core.exceptions import ClaimStoreError
from sci_etl_core.processors.validation import Violation


@dataclass(frozen=True, slots=True, kw_only=True)
class RejectedEntity:
    """An extracted entity that was not kept, with every reason, for review.

    ``entry_id`` is :func:`rejection_id` of the other identifying fields, so
    rejecting the same entity again in a later run gives the same entry.
    ``quote`` is the evidence the model quoted, empty when it quoted none.
    ``created_at`` is an ISO 8601 time with a UTC offset.
    """

    entry_id: str
    record_id: str
    entity: dict[str, Any]
    violations: tuple[Violation, ...]
    stamp: ExtractionStamp | None
    quote: str = ""
    created_at: str


def rejection_id(
    record_id: str, entity: Mapping[str, Any], violations: Sequence[Violation], stamp: ExtractionStamp | None
) -> str:
    """Return the id of a rejection: a digest of its record, entity, violation codes and fields, and stamp."""
    return content_hash(
        [
            record_id,
            _json_ready(entity),
            [[violation.code, violation.field] for violation in violations],
            None if stamp is None else stamp.to_dict(),
        ]
    )


def _json_ready(value: Mapping[str, Any]) -> Any:
    loaded: Any = json.loads(json.dumps(dict(value), ensure_ascii=False, default=str))
    return loaded


class AsyncRejectionStore(ABC):
    """Storage for rejected entities that a reviewer resolves later.

    :class:`~sci_etl_core.llm.extraction_async.AsyncLLMEntityExtractor` puts
    every entity its schema or validator rejects here when given
    ``rejections=``. A rejected *entity* is kept for review; it is unrelated
    to a quarantined *record*, one the pipeline skips after it failed
    ``max_attempts`` times.
    """

    @abstractmethod
    async def put(self, entries: Sequence[RejectedEntity]) -> None:
        """Store ``entries``; an entry whose ``entry_id`` is already stored is left as it is, resolution included.

        Raises:
            ClaimStoreError: The store cannot be written.
        """

    @abstractmethod
    async def unresolved(self, limit: int = 100, after: str | None = None) -> list[RejectedEntity]:
        """Return up to ``limit`` unresolved entries in ``entry_id`` order, after the ``entry_id`` ``after``.

        Raises:
            ValueError: ``limit`` is less than 1.
        """

    @abstractmethod
    async def resolve(self, entry_id: str, resolution: str, corrected: Mapping[str, Any] | None = None) -> None:
        """Record a reviewer's ``resolution`` of an entry, and the ``corrected`` entity if there is one.

        Raises:
            KeyError: No entry has ``entry_id``.
        """

    @abstractmethod
    async def count(self, *, unresolved_only: bool = True) -> int:
        """Return how many entries are stored, or only how many are unresolved."""

    async def aclose(self) -> None:
        """Release the store's resources; the default does nothing."""
        return None


def _check_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be a positive integer")


@dataclass(slots=True)
class _Resolution:
    entry: RejectedEntity
    resolution: str | None = None
    corrected: dict[str, Any] | None = None


class InMemoryRejectionStore(AsyncRejectionStore):
    """A rejection store that lives as long as the process."""

    def __init__(self) -> None:
        self._entries: dict[str, _Resolution] = {}

    async def put(self, entries: Sequence[RejectedEntity]) -> None:
        for entry in entries:
            self._entries.setdefault(entry.entry_id, _Resolution(replace(entry, entity=dict(entry.entity))))

    async def unresolved(self, limit: int = 100, after: str | None = None) -> list[RejectedEntity]:
        _check_limit(limit)
        pending = sorted(
            entry_id
            for entry_id, stored in self._entries.items()
            if stored.resolution is None and (after is None or entry_id > after)
        )
        return [self._entries[entry_id].entry for entry_id in pending[:limit]]

    async def resolve(self, entry_id: str, resolution: str, corrected: Mapping[str, Any] | None = None) -> None:
        stored = self._entries.get(entry_id)
        if stored is None:
            raise KeyError(entry_id)
        stored.resolution = resolution
        stored.corrected = None if corrected is None else dict(corrected)

    async def count(self, *, unresolved_only: bool = True) -> int:
        if not unresolved_only:
            return len(self._entries)
        return sum(1 for stored in self._entries.values() if stored.resolution is None)

    async def resolution_of(self, entry_id: str) -> tuple[str | None, dict[str, Any] | None]:
        """Return the resolution and corrected entity recorded for ``entry_id``.

        Raises:
            KeyError: No entry has ``entry_id``.
        """
        stored = self._entries[entry_id]
        return stored.resolution, stored.corrected


_MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        (
            "CREATE TABLE IF NOT EXISTS rejections ("
            " entry_id TEXT PRIMARY KEY,"
            " record_id TEXT NOT NULL,"
            " entity TEXT NOT NULL,"
            " violations TEXT NOT NULL,"
            " stamp TEXT,"
            " quote TEXT NOT NULL,"
            " created_at TEXT NOT NULL,"
            " resolution TEXT,"
            " corrected TEXT,"
            " resolved_at TEXT)",
            "CREATE INDEX IF NOT EXISTS rejections_record ON rejections(record_id)",
        ),
    ),
)

_COLUMNS = "entry_id, record_id, entity, violations, stamp, quote, created_at"


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _row(entry: RejectedEntity) -> tuple[Any, ...]:
    return (
        entry.entry_id,
        entry.record_id,
        _encode(entry.entity),
        _encode(
            [
                {"code": v.code, "field": v.field, "severity": v.severity, "message": v.message}
                for v in entry.violations
            ]
        ),
        None if entry.stamp is None else _encode(entry.stamp.to_dict()),
        entry.quote,
        entry.created_at,
    )


def _entry(row: Sequence[Any]) -> RejectedEntity:
    entry_id, record_id, entity, violations, stamp, quote, created_at = row
    return RejectedEntity(
        entry_id=entry_id,
        record_id=record_id,
        entity=json.loads(entity),
        violations=tuple(
            Violation(code=v["code"], field=v["field"], severity=v["severity"], message=v["message"])
            for v in json.loads(violations)
        ),
        stamp=None if stamp is None else ExtractionStamp.from_dict(json.loads(stamp)),
        quote=quote,
        created_at=created_at,
    )


class AsyncSqliteRejectionStore(AsyncRejectionStore):
    """A rejection store kept in a SQLite file, so a review can span runs.

    The file and its parent folder are created on first use, and the file
    records its schema version in ``PRAGMA user_version``. Every SQLite
    failure, including a file written by a newer sci-etl-core, raises
    :class:`~sci_etl_core.exceptions.ClaimStoreError`. Close it with
    :meth:`aclose`. Use each instance from one event loop.
    """

    def __init__(self, path: str | Path, now: Callable[[], datetime] | None = None) -> None:
        self._path = Path(path)
        self._now = now or (lambda: datetime.now(UTC))
        self._runner = AsyncSqliteRunner(self._open_connection, error_factory=ClaimStoreError)

    async def put(self, entries: Sequence[RejectedEntity]) -> None:
        rows = [_row(entry) for entry in entries]
        if not rows:
            return

        def insert(connection: sqlite3.Connection) -> None:
            with transaction(connection):
                connection.executemany(
                    f"INSERT OR IGNORE INTO rejections ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", rows
                )

        await self._runner.run(insert, "store rejected entities")

    async def unresolved(self, limit: int = 100, after: str | None = None) -> list[RejectedEntity]:
        _check_limit(limit)
        rows = await self._runner.run(
            lambda connection: connection.execute(
                f"SELECT {_COLUMNS} FROM rejections WHERE resolution IS NULL AND entry_id > ?"
                " ORDER BY entry_id LIMIT ?",
                ("" if after is None else after, limit),
            ).fetchall(),
            "read rejected entities",
        )
        return [_entry(row) for row in rows]

    async def resolve(self, entry_id: str, resolution: str, corrected: Mapping[str, Any] | None = None) -> None:
        stamp = self._now().isoformat()
        payload = None if corrected is None else _encode(dict(corrected))
        cursor = await self._runner.run(
            lambda connection: connection.execute(
                "UPDATE rejections SET resolution = ?, corrected = ?, resolved_at = ? WHERE entry_id = ?",
                (resolution, payload, stamp, entry_id),
            ),
            "resolve a rejected entity",
        )
        if cursor.rowcount == 0:
            raise KeyError(entry_id)

    async def count(self, *, unresolved_only: bool = True) -> int:
        query = "SELECT COUNT(*) FROM rejections" + (" WHERE resolution IS NULL" if unresolved_only else "")
        row = await self._runner.run(
            lambda connection: connection.execute(query).fetchone(), "count rejected entities"
        )
        return int(row[0])

    async def resolution_of(self, entry_id: str) -> tuple[str | None, dict[str, Any] | None]:
        """Return the resolution and corrected entity recorded for ``entry_id``.

        Raises:
            KeyError: No entry has ``entry_id``.
        """
        row = await self._runner.run(
            lambda connection: connection.execute(
                "SELECT resolution, corrected FROM rejections WHERE entry_id = ?", (entry_id,)
            ).fetchone(),
            "read a rejection's resolution",
        )
        if row is None:
            raise KeyError(entry_id)
        return row[0], None if row[1] is None else json.loads(row[1])

    async def aclose(self) -> None:
        """Close the connection; a later call reopens it."""
        await self._runner.aclose()

    def _open_connection(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            migrate(
                connection,
                _MIGRATIONS,
                lambda found, supported: ClaimStoreError(newer_schema_message("rejection store", found, supported)),
            )
        except BaseException:
            connection.close()
            raise
        return connection
