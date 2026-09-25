from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from sci_etl_core._migrations import migrate, schema_version, transaction


class Refused(Exception):
    pass


def _refuse(found: int, supported: int) -> Refused:
    return Refused(f"{found} > {supported}")


def test_each_migration_runs_once_in_order_and_records_its_version():
    applied: list[int] = []
    migrations = [
        (1, ["CREATE TABLE items (name TEXT)", lambda connection: applied.append(1)]),
        (2, [lambda connection: applied.append(2), "ALTER TABLE items ADD COLUMN size INTEGER"]),
    ]
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        migrate(connection, migrations, _refuse)
        migrate(connection, migrations, _refuse)
        assert schema_version(connection) == 2
        assert [row[1] for row in connection.execute("PRAGMA table_info(items)")] == ["name", "size"]
    assert applied == [1, 2]


def test_a_failed_migration_rolls_back_and_keeps_the_previous_version():
    def fail(connection: sqlite3.Connection) -> None:
        raise ValueError("broken step")

    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        migrate(connection, [(1, ["CREATE TABLE items (name TEXT)"])], _refuse)
        with pytest.raises(ValueError, match="broken step"):
            migrate(connection, [(1, []), (2, ["CREATE TABLE other (name TEXT)", fail])], _refuse)
        assert schema_version(connection) == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'other'").fetchone() is None


def test_a_newer_file_is_refused_with_the_store_error():
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        connection.execute("PRAGMA user_version = 5")
        with pytest.raises(Refused, match="5 > 1"):
            migrate(connection, [(1, [])], _refuse)


def _commit_then_fail(connection: sqlite3.Connection) -> None:
    with transaction(connection):
        connection.execute("CREATE TABLE items (name TEXT)")
        connection.execute("COMMIT")
        raise ValueError("after commit")


def test_a_block_that_already_ended_its_transaction_is_not_rolled_back_again():
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        with pytest.raises(ValueError, match="after commit"):
            _commit_then_fail(connection)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'items'").fetchone() == ("items",)
