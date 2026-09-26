from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any, Literal

from sci_etl_core._migrations import Migration, migrate, newer_schema_message, transaction
from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.claims.models import Claim
from sci_etl_core.claims.store_base import (
    AsyncClaimStore,
    ClaimChange,
    ClaimChangePage,
    check_limit,
    unique_claims,
)
from sci_etl_core.exceptions import ClaimStoreError

_MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        (
            "CREATE TABLE IF NOT EXISTS claims ("
            " claim_id TEXT PRIMARY KEY,"
            " record_id TEXT NOT NULL,"
            " position INTEGER NOT NULL,"
            " kind TEXT NOT NULL CHECK (kind IN ('measurement', 'assertion')),"
            " subject TEXT NOT NULL,"
            " predicate TEXT NOT NULL,"
            " object TEXT NOT NULL DEFAULT '',"
            " polarity INTEGER NOT NULL DEFAULT 0 CHECK (polarity IN (-1, 0, 1)),"
            " canonical_value REAL,"
            " canonical_unit TEXT,"
            " quantity_kind TEXT,"
            " span_start INTEGER NOT NULL,"
            " span_end INTEGER NOT NULL,"
            " revision INTEGER NOT NULL,"
            " row TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS claims_record ON claims(record_id, position)",
            "CREATE INDEX IF NOT EXISTS claims_triple ON claims(subject, predicate, object)",
            "CREATE INDEX IF NOT EXISTS claims_kind_value ON claims(quantity_kind, canonical_value)",
            "CREATE TABLE IF NOT EXISTS claim_context ("
            " claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,"
            " key TEXT NOT NULL,"
            " value TEXT NOT NULL,"
            " PRIMARY KEY (claim_id, key, value)) WITHOUT ROWID",
            "CREATE INDEX IF NOT EXISTS claim_context_pair ON claim_context(key, value)",
            "CREATE TABLE IF NOT EXISTS changes ("
            " revision INTEGER PRIMARY KEY,"
            " record_id TEXT NOT NULL,"
            " op TEXT NOT NULL CHECK (op IN ('replace', 'delete')))",
        ),
    ),
)

_INSERT_CLAIM = (
    "INSERT INTO claims (claim_id, record_id, position, kind, subject, predicate, object, polarity,"
    " canonical_value, canonical_unit, quantity_kind, span_start, span_end, revision, row)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _claim_values(claim: Claim, position: int, revision: int) -> tuple[Any, ...]:
    canonical = None if claim.quantity is None else claim.quantity.canonical
    return (
        claim.claim_id,
        claim.span.record_id,
        position,
        claim.kind,
        claim.subject,
        claim.predicate,
        claim.object,
        claim.polarity,
        None if canonical is None else canonical.value,
        None if canonical is None else canonical.unit,
        None if canonical is None else canonical.kind,
        claim.span.start,
        claim.span.end,
        revision,
        json.dumps(claim.to_row(), ensure_ascii=False),
    )


class AsyncSqliteClaimStore(AsyncClaimStore):
    """A claim store kept in a SQLite file.

    Claims are indexed by record, by ``(subject, predicate, object)``, by
    canonical kind and value, and by context pair. The file and its parent
    folder are created on first use, foreign keys are enforced on every
    connection, and the file records its schema version in
    ``PRAGMA user_version``. Every SQLite failure, including a file written by
    a newer sci-etl-core, raises
    :class:`~sci_etl_core.exceptions.ClaimStoreError`. Close it with
    :meth:`aclose`; a later call reopens it. Use each instance from one event
    loop.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._runner = AsyncSqliteRunner(self._open_connection, error_factory=ClaimStoreError)

    async def replace_record(self, record_id: str, claims: Sequence[Claim]) -> int:
        kept = unique_claims(record_id, claims)
        return await self._runner.run(
            lambda connection: self._write(connection, record_id, kept, "replace"), "replace a record's claims"
        )

    async def delete_record(self, record_id: str) -> int:
        return await self._runner.run(
            lambda connection: self._write(connection, record_id, [], "delete"), "delete a record's claims"
        )

    async def claims_for_records(self, record_ids: Collection[str]) -> dict[str, list[Claim]]:
        wanted = list(dict.fromkeys(record_ids))
        if not wanted:
            return {}

        def read(connection: sqlite3.Connection) -> list[tuple[str, str]]:
            rows: list[tuple[str, str]] = []
            for start in range(0, len(wanted), 500):
                chunk = wanted[start : start + 500]
                marks = ", ".join("?" * len(chunk))
                rows.extend(
                    connection.execute(
                        f"SELECT record_id, row FROM claims WHERE record_id IN ({marks}) ORDER BY record_id, position",
                        chunk,
                    ).fetchall()
                )
            return rows

        found: dict[str, list[Claim]] = {}
        for record_id, row in await self._runner.run(read, "read claims"):
            found.setdefault(record_id, []).append(Claim.from_row(json.loads(row)))
        return {record_id: found[record_id] for record_id in wanted if record_id in found}

    async def changes_since(self, revision: int, limit: int = 1000) -> ClaimChangePage:
        check_limit(limit)
        rows = await self._runner.run(
            lambda connection: connection.execute(
                "SELECT revision, record_id, op FROM changes WHERE revision > ? ORDER BY revision LIMIT ?",
                (revision, limit),
            ).fetchall(),
            "read claim changes",
        )
        changes = tuple(ClaimChange(revision=row[0], record_id=row[1], op=row[2]) for row in rows)
        return ClaimChangePage(changes=changes, next_revision=changes[-1].revision if changes else revision)

    async def revision(self) -> int:
        row = await self._runner.run(
            lambda connection: connection.execute("SELECT COALESCE(MAX(revision), 0) FROM changes").fetchone(),
            "read the claim revision",
        )
        return int(row[0])

    async def count(self) -> int:
        row = await self._runner.run(
            lambda connection: connection.execute("SELECT COUNT(*) FROM claims").fetchone(), "count claims"
        )
        return int(row[0])

    async def aclose(self) -> None:
        """Close the connection; a later call reopens it."""
        await self._runner.aclose()

    @staticmethod
    def _write(
        connection: sqlite3.Connection, record_id: str, claims: list[Claim], op: Literal["replace", "delete"]
    ) -> int:
        with transaction(connection):
            connection.execute("DELETE FROM claims WHERE record_id = ?", (record_id,))
            cursor = connection.execute("INSERT INTO changes (record_id, op) VALUES (?, ?)", (record_id, op))
            revision = int(cursor.lastrowid or 0)
            connection.executemany(
                _INSERT_CLAIM, [_claim_values(claim, position, revision) for position, claim in enumerate(claims)]
            )
            connection.executemany(
                "INSERT INTO claim_context (claim_id, key, value) VALUES (?, ?, ?)",
                [(claim.claim_id, key, value) for claim in claims for key, value in claim.context.attributes],
            )
        return revision

    def _open_connection(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            migrate(
                connection,
                _MIGRATIONS,
                lambda found, supported: ClaimStoreError(newer_schema_message("claim store", found, supported)),
            )
        except BaseException:
            connection.close()
            raise
        return connection
