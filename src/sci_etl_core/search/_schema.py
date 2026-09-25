from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from sci_etl_core._migrations import Migration, migrate, newer_schema_message, transaction
from sci_etl_core.exceptions import SearchStoreError

FACET_KEYS_SETTING = "facet_keys"

_V1_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS documents (
        doc_id     INTEGER PRIMARY KEY,
        record_id  TEXT    NOT NULL UNIQUE,
        title      TEXT    NOT NULL DEFAULT '',
        abstract   TEXT    NOT NULL DEFAULT '',
        body       TEXT    NOT NULL DEFAULT '',
        metadata   TEXT    NOT NULL DEFAULT '{}',
        indexed_at TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_tags (
        doc_id INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        key    TEXT    NOT NULL,
        value  TEXT    NOT NULL,
        PRIMARY KEY (doc_id, key, value)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS document_tags_key_value ON document_tags(key, value, doc_id)",
    """
    CREATE TABLE IF NOT EXISTS index_settings (
        name  TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
        title, abstract, body,
        content='documents',
        content_rowid='doc_id',
        tokenize="unicode61 remove_diacritics 2"
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
        INSERT INTO documents_fts(rowid, title, abstract, body)
        VALUES (new.doc_id, new.title, new.abstract, new.body);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
        INSERT INTO documents_fts(documents_fts, rowid, title, abstract, body)
        VALUES ('delete', old.doc_id, old.title, old.abstract, old.body);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
        INSERT INTO documents_fts(documents_fts, rowid, title, abstract, body)
        VALUES ('delete', old.doc_id, old.title, old.abstract, old.body);
        INSERT INTO documents_fts(rowid, title, abstract, body)
        VALUES (new.doc_id, new.title, new.abstract, new.body);
    END
    """,
)

MIGRATIONS: tuple[Migration, ...] = ((1, _V1_DDL),)
SCHEMA_VERSION = MIGRATIONS[-1][0]


def bootstrap(connection: sqlite3.Connection, facet_keys: Iterable[str]) -> None:
    """Configure ``connection`` and bring the search index's schema up to date.

    Foreign keys are enforced, so deleting a document deletes its tags. Each
    migration in :data:`MIGRATIONS` newer than the file's ``PRAGMA user_version``
    runs in its own transaction. A migration is only ever appended, never
    rewritten.

    An index with no persisted facet keys and no documents adopts ``facet_keys``:
    there is nothing to tag yet. An index with documents but no persisted facet
    keys was written without this store, so no keys are adopted, and every
    filter or facet raises until ``rebuild_tags()`` runs.

    Raises:
        SearchStoreError: The file's schema is newer than this library knows.
        sqlite3.Error: The file cannot be read or migrated.
    """
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    migrate(
        connection,
        MIGRATIONS,
        lambda found, supported: SearchStoreError(newer_schema_message("search index", found, supported)),
    )
    if _is_untagged_and_empty(connection):
        with transaction(connection):
            if _is_untagged_and_empty(connection):
                write_facet_keys(connection, facet_keys)


def read_facet_keys(connection: sqlite3.Connection) -> frozenset[str]:
    """Return the facet keys whose tags are materialized, or none if the index never recorded any.

    Raises:
        SearchStoreError: The recorded value is not a JSON list of strings.
    """
    row = connection.execute("SELECT value FROM index_settings WHERE name = ?", (FACET_KEYS_SETTING,)).fetchone()
    if row is None:
        return frozenset()
    try:
        keys = json.loads(row[0])
    except ValueError:
        keys = None
    if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
        raise SearchStoreError("The search index's recorded facet keys are unreadable; call rebuild_tags()")
    return frozenset(keys)


def write_facet_keys(connection: sqlite3.Connection, facet_keys: Iterable[str]) -> None:
    """Record ``facet_keys`` as the keys whose tags are materialized."""
    connection.execute(
        "INSERT INTO index_settings (name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
        (FACET_KEYS_SETTING, json.dumps(sorted(set(facet_keys)))),
    )


def _is_untagged_and_empty(connection: sqlite3.Connection) -> bool:
    recorded = connection.execute("SELECT 1 FROM index_settings WHERE name = ?", (FACET_KEYS_SETTING,)).fetchone()
    return recorded is None and connection.execute("SELECT 1 FROM documents LIMIT 1").fetchone() is None
