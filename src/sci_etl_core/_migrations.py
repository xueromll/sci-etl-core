from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

Step = str | Callable[[sqlite3.Connection], None]
Migration = tuple[int, Sequence[Step]]


@contextmanager
def transaction(connection: sqlite3.Connection, mode: str = "IMMEDIATE") -> Iterator[None]:
    """Run the block in one explicit transaction.

    ``mode`` is ``"IMMEDIATE"`` for a write, which takes the write lock up
    front, or ``"DEFERRED"`` for a consistent read. The transaction is rolled
    back if the block raises.
    """
    connection.execute(f"BEGIN {mode}")
    try:
        yield
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def schema_version(connection: sqlite3.Connection) -> int:
    """Return the file's ``PRAGMA user_version``."""
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def migrate(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration],
    future_version_error: Callable[[int, int], Exception],
) -> None:
    """Bring a SQLite file's schema up to the newest version in ``migrations``.

    ``migrations`` is a list of ``(version, steps)`` in increasing version
    order, where each step is an SQL statement or a callable that receives the
    connection. Each migration newer than the file's ``PRAGMA user_version``
    runs in its own transaction and then records its version, so an
    interrupted upgrade resumes where it stopped. A migration is only ever
    appended, never rewritten. A file with ``user_version = 0`` is migrated
    from the start, so version 1 must accept tables that already exist.

    Raises:
        Exception: The file's version is newer than the last migration; the
            exception is ``future_version_error(found, supported)``, so each
            store raises its own type.
        sqlite3.Error: The file cannot be read or migrated.
    """
    supported = migrations[-1][0]
    found = schema_version(connection)
    if found > supported:
        raise future_version_error(found, supported)
    for version, steps in migrations:
        if found >= version:
            continue
        with transaction(connection):
            for step in steps:
                if isinstance(step, str):
                    connection.execute(step)
                else:
                    step(connection)
            connection.execute(f"PRAGMA user_version = {version}")


def newer_schema_message(store: str, found: int, supported: int) -> str:
    """Describe a file written by a newer sci-etl-core."""
    return (
        f"The {store} has schema version {found}, newer than version {supported} "
        "that this sci-etl-core supports; upgrade sci-etl-core to open it"
    )
