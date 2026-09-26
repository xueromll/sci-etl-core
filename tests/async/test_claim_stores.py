from __future__ import annotations

import asyncio
import dataclasses
import sqlite3

import pytest
import pytest_asyncio

from sci_etl_core.claims.drafts import ClaimDraft, QuantityDraft
from sci_etl_core.claims.models import CanonicalValue, Claim, EvidenceSpan, ExtractionStamp
from sci_etl_core.claims.store_base import ClaimChange
from sci_etl_core.claims.store_memory import InMemoryClaimStore
from sci_etl_core.claims.store_sqlite_async import AsyncSqliteClaimStore
from sci_etl_core.exceptions import ClaimStoreError

STAMP = ExtractionStamp(model="m", prompt_hash="p", schema_hash="s", extractor_version="v")


def claim(record_id: str, subject: str, *, start: int = 0, band: str = "g") -> Claim:
    draft = ClaimDraft(
        kind="measurement",
        subject=subject,
        predicate="effective_radius",
        quantity=QuantityDraft(verbatim="2.9 kpc", value=2.9, unit_text="kpc"),
        context={"band": band},
        quote="Re = 2.9 kpc",
    )
    span = EvidenceSpan(record_id=record_id, start=start, end=start + 10, quote="Re = 2.9 kpc")
    return Claim.from_draft(draft, span=span, stamp=STAMP)


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryClaimStore()
        return
    sqlite_store = AsyncSqliteClaimStore(tmp_path / "nested" / "claims.db")
    yield sqlite_store
    await sqlite_store.aclose()


class TestClaimStoreParity:
    @pytest.mark.asyncio
    async def test_replace_then_read_back_in_order(self, store):
        claims = [claim("r1", "DF44"), claim("r1", "DF2", start=20), claim("r2", "VCC1287")]
        await store.replace_record("r1", claims[:2])
        await store.replace_record("r2", claims[2:])

        assert await store.claims_for_records(["r2", "r1", "missing"]) == {"r2": claims[2:], "r1": claims[:2]}
        assert await store.count() == 3

    @pytest.mark.asyncio
    async def test_replacing_a_record_drops_its_old_claims(self, store):
        await store.replace_record("r1", [claim("r1", "DF44"), claim("r1", "DF2", start=20)])
        await store.replace_record("r1", [claim("r1", "DF4")])

        assert [item.subject for item in (await store.claims_for_records(["r1"]))["r1"]] == ["DF4"]

    @pytest.mark.asyncio
    async def test_an_empty_replace_clears_the_record_and_still_records_a_change(self, store):
        await store.replace_record("r1", [claim("r1", "DF44")])
        revision = await store.replace_record("r1", [])

        assert await store.claims_for_records(["r1"]) == {}
        assert revision == 2
        assert (await store.changes_since(1)).changes == (ClaimChange(revision=2, record_id="r1", op="replace"),)

    @pytest.mark.asyncio
    async def test_a_repeated_claim_id_keeps_the_first(self, store, caplog):
        first = claim("r1", "DF44")
        repeat = dataclasses.replace(first, confidence=0.1)

        with caplog.at_level("INFO", logger="sci_etl_core.claims.store_base"):
            await store.replace_record("r1", [first, repeat])

        assert (await store.claims_for_records(["r1"]))["r1"] == [first]
        assert caplog.messages == ["Dropped 1 repeated claims of record r1"]

    @pytest.mark.asyncio
    async def test_a_claim_of_another_record_is_refused(self, store):
        with pytest.raises(ValueError, match="belongs to 'r2', not 'r1'"):
            await store.replace_record("r1", [claim("r2", "DF44")])

    @pytest.mark.asyncio
    async def test_delete_removes_claims_and_records_a_delete(self, store):
        await store.replace_record("r1", [claim("r1", "DF44")])

        assert await store.delete_record("r1") == 2
        assert await store.count() == 0
        assert (await store.changes_since(0)).changes[-1].op == "delete"

    @pytest.mark.asyncio
    async def test_revisions_only_grow_and_changes_page_by_revision(self, store):
        assert await store.revision() == 0
        revisions = [await store.replace_record(f"r{number}", []) for number in range(5)]

        first = await store.changes_since(0, limit=2)
        rest = await store.changes_since(first.next_revision, limit=10)
        empty = await store.changes_since(rest.next_revision)

        assert revisions == [1, 2, 3, 4, 5]
        assert await store.revision() == 5
        assert [change.record_id for change in first.changes + rest.changes] == [f"r{n}" for n in range(5)]
        assert (empty.changes, empty.next_revision) == ((), 5)

    @pytest.mark.asyncio
    async def test_a_limit_below_one_is_rejected(self, store):
        with pytest.raises(ValueError, match="limit"):
            await store.changes_since(0, limit=0)

    @pytest.mark.asyncio
    async def test_reading_no_records_reads_nothing(self, store):
        assert await store.claims_for_records([]) == {}


class TestSqliteClaimStore:
    @pytest.mark.asyncio
    async def test_claims_survive_reopening_and_context_rows_cascade(self, tmp_path):
        path = tmp_path / "claims.db"
        store = AsyncSqliteClaimStore(path)
        canonical = CanonicalValue(
            value=2.9, uncertainty=None, unit="kpc", dimension=(("L", 1),), kind="length", conversion_path=()
        )
        stored = claim("r1", "DF44")
        stored = dataclasses.replace(stored, quantity=dataclasses.replace(stored.quantity, canonical=canonical))
        await store.replace_record("r1", [stored])
        await store.aclose()

        reopened = AsyncSqliteClaimStore(path)
        assert await reopened.claims_for_records(["r1"]) == {"r1": [stored]}
        await reopened.replace_record("r1", [])
        await reopened.aclose()

        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM claim_context").fetchone() == (0,)

    @pytest.mark.asyncio
    async def test_many_records_are_read_in_chunks(self, tmp_path):
        store = AsyncSqliteClaimStore(tmp_path / "claims.db")
        for number in range(3):
            await store.replace_record(f"r{number}", [claim(f"r{number}", "DF44")])

        found = await store.claims_for_records([f"r{number}" for number in range(1200)])

        assert sorted(found) == ["r0", "r1", "r2"]
        await store.aclose()

    @pytest.mark.asyncio
    async def test_a_file_from_a_newer_release_is_refused(self, tmp_path):
        path = tmp_path / "claims.db"
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA user_version = 99")
        store = AsyncSqliteClaimStore(path)

        with pytest.raises(ClaimStoreError, match="claim store has schema version 99"):
            await store.count()
        await store.aclose()

    @pytest.mark.asyncio
    async def test_a_cancelled_replace_leaves_the_store_usable(self, tmp_path):
        store = AsyncSqliteClaimStore(tmp_path / "claims.db")
        task = asyncio.ensure_future(store.replace_record("r1", [claim("r1", "DF44")]))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await store.replace_record("r2", [claim("r2", "DF2")])
        assert "r2" in await store.claims_for_records(["r1", "r2"])
        await store.aclose()


class TestDefaultClose:
    @pytest.mark.asyncio
    async def test_the_in_memory_store_closes_without_doing_anything(self):
        assert await InMemoryClaimStore().aclose() is None
