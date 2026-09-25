"""Files written by sci-etl-core 0.4.0 open in this release.

Each test copies the committed fixtures into a temporary folder first, so the
upgrade a store performs on open never changes the committed files.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sci_etl_core import (
    AsyncFileStateManager,
    AsyncSqliteEmbeddingStore,
    AsyncSqliteLLMResponseCache,
    AsyncSqliteStateManager,
)
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store

FIXTURES = Path(__file__).with_name("v0_4_0")
PROCESSED = {"2401.00001v1", "2401.00002v1"}


@pytest.fixture
def files(tmp_path: Path) -> Path:
    copy = tmp_path / "v0_4_0"
    shutil.copytree(FIXTURES, copy)
    return copy


def _user_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


@pytest.mark.asyncio
async def test_the_sqlite_state_database_is_upgraded_and_its_offset_becomes_the_cursor(files):
    assert _user_version(files / "state.sqlite") == 0
    state = AsyncSqliteStateManager(files / "state.sqlite")

    assert await state.load_processed_ids() == PROCESSED
    metadata = await state.load_metadata()
    assert (metadata.cursor, metadata.truncated) == ("40", False)
    assert (metadata.head_ids, metadata.head_offset, metadata.tail_ids) == (["2401.00009v1"], 0, ["2401.00005v1"])
    assert await state.failure_counts() == {}
    await state.aclose()

    assert _user_version(files / "state.sqlite") == 2


@pytest.mark.asyncio
async def test_the_file_state_is_read_and_rewritten_in_the_current_format(files):
    state = AsyncFileStateManager(files / "processed_ids.txt", files / "metadata.json")

    assert await state.load_processed_ids() == PROCESSED
    metadata = await state.load_metadata()
    assert (metadata.cursor, metadata.head_ids, metadata.tail_ids) == ("40", ["2401.00009v1"], ["2401.00005v1"])

    await state.save_metadata(metadata)
    written = json.loads((files / "metadata.json").read_text(encoding="utf-8"))
    assert (written["schema_version"], written["cursor"], written["failures"]) == (2, "40", {})
    assert "last_start_index" not in written


@pytest.mark.asyncio
async def test_the_llm_cache_serves_its_responses(files):
    cache = AsyncSqliteLLMResponseCache(files / "llm_cache.sqlite")

    assert await cache.get("key") == {"relevant": True}
    await cache.aclose()

    assert _user_version(files / "llm_cache.sqlite") == 1


@pytest.mark.asyncio
async def test_the_embedding_store_serves_its_chunks(files):
    store = AsyncSqliteEmbeddingStore(files / "embeddings.sqlite")

    assert await store.count() == 1
    [hit] = await store.query([0.6, 0.8], top_k=1)
    assert (hit.record_id, hit.text) == ("2401.00001v1", "dwarf galaxies")
    await store.aclose()

    assert _user_version(files / "embeddings.sqlite") == 1


@pytest.mark.asyncio
async def test_the_search_index_serves_its_documents(files):
    index = AsyncSqliteFts5Store(files / "search.sqlite", facet_keys=("categories",))

    documents = await index.get_documents(["2401.00001v1"])
    assert documents["2401.00001v1"].title == "Dwarf galaxies"
    await index.aclose()

    assert _user_version(files / "search.sqlite") == 1
