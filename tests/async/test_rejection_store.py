from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from sci_etl_core.claims.models import ExtractionStamp
from sci_etl_core.claims.rejections import (
    AsyncSqliteRejectionStore,
    InMemoryRejectionStore,
    RejectedEntity,
    rejection_id,
)
from sci_etl_core.exceptions import ClaimStoreError
from sci_etl_core.processors.validation import Violation

STAMP = ExtractionStamp(model="m", prompt_hash="p", schema_hash="", extractor_version="sci-etl-core/0.6.0")
VIOLATION = Violation(code="out-of-range", field="ra", severity="error", message="ra is 400, outside [0, 360]")


def entry(number: int, *, stamp: ExtractionStamp | None = STAMP) -> RejectedEntity:
    entity = {"name": f"G{number}", "ra": 400 + number}
    return RejectedEntity(
        entry_id=rejection_id("r1", entity, (VIOLATION,), stamp),
        record_id="r1",
        entity=entity,
        violations=(VIOLATION,),
        stamp=stamp,
        quote=f"quote {number}",
        created_at="2026-09-26T00:00:00+00:00",
    )


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryRejectionStore()
        return
    sqlite_store = AsyncSqliteRejectionStore(
        tmp_path / "nested" / "rejections.db", now=lambda: datetime(2026, 9, 27, tzinfo=UTC)
    )
    yield sqlite_store
    await sqlite_store.aclose()


class TestRejectionStoreParity:
    @pytest.mark.asyncio
    async def test_put_then_read_back_every_field(self, store):
        stored = [entry(1), entry(2, stamp=None)]
        await store.put(stored)

        assert await store.unresolved() == sorted(stored, key=lambda item: item.entry_id)

    @pytest.mark.asyncio
    async def test_putting_an_entry_again_keeps_one_and_its_resolution(self, store):
        await store.put([entry(1)])
        await store.resolve(entry(1).entry_id, "accepted", {"name": "G1", "ra": 40})
        await store.put([entry(1)])

        assert await store.count(unresolved_only=False) == 1
        assert await store.count() == 0
        assert await store.resolution_of(entry(1).entry_id) == ("accepted", {"name": "G1", "ra": 40})

    @pytest.mark.asyncio
    async def test_unresolved_pages_in_entry_id_order(self, store):
        entries = sorted((entry(number) for number in range(5)), key=lambda item: item.entry_id)
        await store.put(entries)

        first = await store.unresolved(limit=2)
        rest = await store.unresolved(limit=10, after=first[-1].entry_id)

        assert first + rest == entries

    @pytest.mark.asyncio
    async def test_resolve_without_a_correction(self, store):
        await store.put([entry(1)])
        await store.resolve(entry(1).entry_id, "rejection upheld")

        assert await store.unresolved() == []
        assert await store.resolution_of(entry(1).entry_id) == ("rejection upheld", None)

    @pytest.mark.asyncio
    async def test_resolving_an_unknown_entry_raises_key_error(self, store):
        with pytest.raises(KeyError):
            await store.resolve("missing", "accepted")
        with pytest.raises(KeyError):
            await store.resolution_of("missing")

    @pytest.mark.asyncio
    async def test_a_limit_below_one_is_rejected(self, store):
        with pytest.raises(ValueError, match="limit"):
            await store.unresolved(limit=0)

    @pytest.mark.asyncio
    async def test_putting_nothing_changes_nothing(self, store):
        await store.put([])

        assert await store.count(unresolved_only=False) == 0


class TestSqliteRejectionStore:
    @pytest.mark.asyncio
    async def test_entries_survive_reopening(self, tmp_path):
        path = tmp_path / "rejections.db"
        first = AsyncSqliteRejectionStore(path)
        await first.put([entry(1)])
        await first.aclose()

        second = AsyncSqliteRejectionStore(path)
        assert await second.unresolved() == [entry(1)]
        await second.aclose()

    @pytest.mark.asyncio
    async def test_a_file_from_a_newer_release_is_refused(self, tmp_path):
        path = tmp_path / "rejections.db"
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA user_version = 99")
        connection.close()
        store = AsyncSqliteRejectionStore(path)

        with pytest.raises(ClaimStoreError, match="schema version 99"):
            await store.count()
        await store.aclose()

    @pytest.mark.asyncio
    async def test_the_default_store_close_does_nothing(self):
        assert await InMemoryRejectionStore().aclose() is None
