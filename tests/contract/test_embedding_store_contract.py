from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore
from sci_etl_core.embeddings.store_memory import InMemoryEmbeddingStore
from sci_etl_core.embeddings.store_sqlite_async import AsyncSqliteEmbeddingStore
from sci_etl_core.testing import EmbeddingStoreContract


class VectorsOnly(InMemoryEmbeddingStore):
    iter_records = AsyncEmbeddingStore.iter_records


def _write_user_version(path, version: int) -> None:
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute(f"PRAGMA user_version = {version}")


class TestInMemoryEmbeddingStore(EmbeddingStoreContract):
    @pytest.fixture
    def make_store(self):
        store = InMemoryEmbeddingStore()
        return lambda: store


class TestAsyncSqliteEmbeddingStore(EmbeddingStoreContract):
    @pytest.fixture
    def make_store(self, tmp_path):
        return lambda: AsyncSqliteEmbeddingStore(tmp_path / "vectors.db")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        return lambda: _write_user_version(tmp_path / "vectors.db", 99)


class TestStoreWithoutIterRecords(EmbeddingStoreContract):
    @pytest.fixture
    def make_store(self):
        store = VectorsOnly()
        return lambda: store
