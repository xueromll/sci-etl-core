from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager
from sci_etl_core.state.async_file_state import AsyncFileStateManager
from sci_etl_core.state.sqlite_async import AsyncSqliteStateManager
from sci_etl_core.testing import StateManagerContract


def _write_user_version(path, version: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute(f"PRAGMA user_version = {version}")


class MinimalState(AsyncStateManager):
    def __init__(self) -> None:
        self.processed: set[str] = set()
        self.metadata = PipelineMetadata()

    async def load_processed_ids(self) -> set[str]:
        return set(self.processed)

    async def mark_processed(self, record_id: str) -> None:
        self.processed.add(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return PipelineMetadata(
            last_run_at=self.metadata.last_run_at,
            cursor=self.metadata.cursor,
            truncated=self.metadata.truncated,
            head_ids=list(self.metadata.head_ids),
            head_offset=self.metadata.head_offset,
            tail_ids=list(self.metadata.tail_ids),
        )

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        self.metadata = metadata


class TestAsyncFileStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: AsyncFileStateManager(tmp_path / "processed.txt", tmp_path / "metadata.json")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        return lambda: (tmp_path / "metadata.json").write_text(json.dumps({"schema_version": 99}), encoding="utf-8")


class TestAsyncSqliteStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: AsyncSqliteStateManager(tmp_path / "nested" / "state.db")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        return lambda: _write_user_version(tmp_path / "nested" / "state.db", 99)


class TestMinimalStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self):
        state = MinimalState()
        return lambda: state
