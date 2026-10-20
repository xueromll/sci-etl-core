"""Files written by sci-etl-core 0.6.0 open in this release.

Each test copies the committed fixtures into a temporary folder first, so the
upgrade a store performs on open never changes the committed files.
"""

from __future__ import annotations

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
from sci_etl_core.claims import AsyncSqliteClaimStore, AsyncSqliteRejectionStore
from sci_etl_core.exporters import read_jsonl_export
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store

FIXTURES = Path(__file__).with_name("v0_6_0")
PROCESSED = {"2401.00001v1", "2401.00002v1"}
FAILURES = {"2401.00003v1": 1}


@pytest.fixture
def files(tmp_path: Path) -> Path:
    copy = tmp_path / "v0_6_0"
    shutil.copytree(FIXTURES, copy)
    return copy


def _user_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


@pytest.mark.asyncio
async def test_the_sqlite_state_database_keeps_its_cursor_and_failures(files):
    state = AsyncSqliteStateManager(files / "state.sqlite")

    assert await state.load_processed_ids() == PROCESSED
    metadata = await state.load_metadata()
    assert (metadata.cursor, metadata.truncated) == ("40", False)
    assert (metadata.head_ids, metadata.head_offset, metadata.tail_ids) == (["2401.00009v1"], 0, ["2401.00005v1"])
    assert await state.failure_counts() == FAILURES
    await state.aclose()

    assert _user_version(files / "state.sqlite") == 2


@pytest.mark.asyncio
async def test_the_file_state_keeps_its_cursor_and_failures(files):
    state = AsyncFileStateManager(files / "processed_ids.txt", files / "metadata.json")

    assert await state.load_processed_ids() == PROCESSED
    metadata = await state.load_metadata()
    assert (metadata.cursor, metadata.head_ids, metadata.tail_ids) == ("40", ["2401.00009v1"], ["2401.00005v1"])
    assert await state.failure_counts() == FAILURES


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


@pytest.mark.asyncio
async def test_the_claim_store_serves_its_claims(files):
    store = AsyncSqliteClaimStore(files / "claims.sqlite")

    [claim] = (await store.claims_for_records(["2401.00001v1"]))["2401.00001v1"]
    assert (claim.kind, claim.subject, claim.predicate) == ("measurement", "DF44", "stellar mass")
    assert claim.confidence == 0.9
    assert claim.quantity is not None
    assert (claim.quantity.verbatim, claim.quantity.value, claim.quantity.unit_text) == ("3e8 M_sun", 3e8, "M_sun")
    assert (claim.span.start, claim.span.end, claim.span.quote) == (0, 40, "DF44 has a stellar mass of 3e8 M_sun.")
    assert claim.context.to_dict() == {"band": "V"}
    assert (claim.stamp.model, claim.stamp.schema_hash, claim.stamp.extractor_version) == ("model-a", "schema", "0.6.0")
    await store.aclose()

    assert _user_version(files / "claims.sqlite") == 1


@pytest.mark.asyncio
async def test_the_rejection_store_keeps_its_entries_and_resolutions(files):
    store = AsyncSqliteRejectionStore(files / "rejections.sqlite")

    assert (await store.count(unresolved_only=False), await store.count()) == (2, 1)
    [entry] = await store.unresolved()
    assert (entry.record_id, entry.entity) == ("2401.00001v1", {"subject": "DF44", "value": -1})
    assert entry.quote == "a negative value"
    assert [(violation.code, violation.field) for violation in entry.violations] == [("out-of-range", "value")]
    assert entry.stamp is not None
    assert (entry.stamp.model, entry.created_at) == ("model-a", "2026-09-27T00:00:00+00:00")
    await store.aclose()

    assert _user_version(files / "rejections.sqlite") == 1


def test_the_jsonl_export_reads_back_every_record(files):
    assert read_jsonl_export(files / "export.jsonl") == {"2401.00001v1": [{"name": "DF44"}], "2401.00002v1": []}
