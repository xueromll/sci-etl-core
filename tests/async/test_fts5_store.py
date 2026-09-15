from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from sci_etl_core.exceptions import SearchStoreError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.search.filters import MetadataFilter
from sci_etl_core.search.query import Term
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store, fts5_available
from sci_etl_core.state.async_base import AsyncStateManager


@asynccontextmanager
async def opened(path, **options):
    store = AsyncSqliteFts5Store(path, **options)
    try:
        yield store
    finally:
        await store.aclose()


def raw(path, sql, parameters=()):
    connection = sqlite3.connect(path)
    try:
        with connection:
            return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


def document(record_id, title="galaxy", **metadata):
    return SearchDocument(record_id, title=title, metadata=metadata)


class NoFts5Connection(sqlite3.Connection):
    def execute(self, sql, *parameters):
        if "USING fts5" in sql:
            raise sqlite3.OperationalError("no such module: fts5")
        return super().execute(sql, *parameters)


class TestCapabilityProbe:
    def test_this_sqlite_supports_what_the_store_needs(self):
        assert sqlite3.sqlite_version_info >= (3, 24, 0), sqlite3.sqlite_version
        assert fts5_available()

    def test_a_connection_that_cannot_open_reports_no_fts5(self):
        def refuse():
            raise sqlite3.OperationalError("unable to open database file")

        assert fts5_available(refuse) is False

    def test_a_build_without_the_fts5_module_reports_no_fts5(self):
        assert fts5_available(lambda: sqlite3.connect(":memory:", factory=NoFts5Connection)) is False

    def test_sqlite3_connect_is_looked_up_when_the_probe_runs(self, mocker, tmp_path):
        mocker.patch.object(sqlite3, "connect", side_effect=sqlite3.OperationalError("no such module: fts5"))
        assert fts5_available() is False
        with pytest.raises(SearchStoreError, match="built without FTS5"):
            AsyncSqliteFts5Store(tmp_path / "search.db")


class TestSchema:
    @pytest.mark.asyncio
    async def test_a_new_file_gets_the_current_schema(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("year", "categories")) as store:
            assert await store.count() == 0
            assert raw(path, "PRAGMA user_version") == [(1,)]
            names = raw(
                path,
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite%' AND name NOT LIKE 'documents_fts_%'"
                " ORDER BY name",
            )
            assert [name for (name,) in names] == [
                "document_tags",
                "document_tags_key_value",
                "documents",
                "documents_ad",
                "documents_ai",
                "documents_au",
                "documents_fts",
                "index_settings",
            ]
            assert raw(path, "SELECT name, value FROM index_settings") == [("facet_keys", '["categories", "year"]')]

    @pytest.mark.asyncio
    async def test_reopening_keeps_the_data_and_the_schema_version(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path) as store:
            await store.index([document("r1")])
        async with opened(path) as reopened:
            assert await reopened.count() == 1
        assert raw(path, "PRAGMA user_version") == [(1,)]

    @pytest.mark.asyncio
    async def test_a_schema_newer_than_this_library_is_refused(self, tmp_path):
        path = tmp_path / "search.db"
        raw(path, "PRAGMA user_version = 2")
        async with opened(path) as store:
            with pytest.raises(SearchStoreError, match="schema version 2, newer than version 1"):
                await store.count()

    @pytest.mark.asyncio
    async def test_a_file_that_is_not_a_database_raises_a_store_error(self, tmp_path):
        path = tmp_path / "search.db"
        path.write_bytes(b"this is not a SQLite database" * 64)
        async with opened(path) as store:
            with pytest.raises(SearchStoreError, match="Failed to open the SQLite search index"):
                await store.count()

    @pytest.mark.asyncio
    async def test_a_path_that_cannot_be_opened_raises_a_store_error(self, tmp_path):
        async with opened(tmp_path / "missing" / "search.db") as store:
            with pytest.raises(SearchStoreError, match="Failed to open the SQLite search index"):
                await store.count()


class TestWrites:
    @pytest.mark.asyncio
    async def test_indexed_at_is_the_injected_utc_time_in_iso_8601(self, tmp_path):
        path = tmp_path / "search.db"
        moment = datetime(2026, 9, 15, 8, 20, 9, 59743, tzinfo=timezone.utc)
        async with opened(path, now=lambda: moment) as store:
            await store.index([document("r1")])
            assert raw(path, "SELECT indexed_at FROM documents") == [("2026-09-15T08:20:09.059743+00:00",)]

    @pytest.mark.asyncio
    async def test_the_default_clock_writes_utc_with_an_offset(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path) as store:
            await store.index([document("r1")])
            ((indexed_at,),) = raw(path, "SELECT indexed_at FROM documents")
            assert datetime.fromisoformat(indexed_at).utcoffset().total_seconds() == 0

    @pytest.mark.asyncio
    async def test_metadata_json_cannot_hold_is_encoded_instead_of_failing_the_write(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path) as store:
            published = datetime(2026, 9, 15, tzinfo=timezone.utc)
            await store.index([document("r1", published=published, raw=b"x", author="Müller")])
            assert raw(path, "SELECT metadata FROM documents") == [
                ('{"published": "2026-09-15T00:00:00+00:00", "raw": "b\'x\'", "author": "Müller"}',)
            ]

    @pytest.mark.asyncio
    async def test_reindexing_keeps_the_row_and_replaces_its_tags(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("year",)) as store:
            await store.index([document("r1", year="2024")])
            ((doc_id,),) = raw(path, "SELECT doc_id FROM documents")
            await store.index([document("r1", year="2024")])
            await store.index([document("r1", year="2025")])
            assert raw(path, "SELECT doc_id FROM documents") == [(doc_id,)]
            assert raw(path, "SELECT doc_id, key, value FROM document_tags") == [(doc_id, "year", "2025")]

    @pytest.mark.asyncio
    async def test_deleting_a_record_leaves_no_orphaned_tags(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("year",)) as store:
            await store.index([document("r1", year="2024"), document("r2", year="2025")])
            await store.delete_record("r1")
            assert raw(path, "SELECT value FROM document_tags") == [("2025",)]

    @pytest.mark.asyncio
    async def test_more_documents_than_one_read_batch_are_returned(self, tmp_path):
        async with opened(tmp_path / "search.db") as store:
            await store.index([document(f"r{index:04d}") for index in range(1_203)])
            wanted = [f"r{index:04d}" for index in range(1_203)] + ["unknown"]
            assert len(await store.get_documents(wanted)) == 1_203


class TestMaintenance:
    @pytest.mark.asyncio
    async def test_integrity_check_detects_an_out_of_band_write_and_rebuild_index_repairs_it(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path) as store:
            await store.index([document("r1", title="dwarf"), document("r2", title="giant")])
            await store.index([document("r1", title="quasar")])
            await store.delete_record("r2")
            await store.optimize()
            assert await store.integrity_check() is True
            raw(path, "DROP TRIGGER documents_au")
            raw(path, "UPDATE documents SET title = 'pulsar' WHERE record_id = 'r1'")
            assert await store.integrity_check() is False
            await store.rebuild_index()
            assert await store.integrity_check() is True
            assert await store.filter_ids(Term("pulsar")) == frozenset({"r1"})
            assert await store.filter_ids(Term("quasar")) == frozenset()

    @pytest.mark.asyncio
    async def test_an_integrity_check_that_cannot_run_raises(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path) as store:
            await store.index([document("r1")])
            raw(path, "DROP TABLE documents_fts")
            with pytest.raises(SearchStoreError, match="Failed to check the search index"):
                await store.integrity_check()

    @pytest.mark.asyncio
    async def test_a_key_added_later_raises_until_its_tags_are_rebuilt(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("categories",)) as first:
            await first.index([document("r1", categories=["GA"], year="2024")])
        async with opened(path, facet_keys=("categories", "year")) as second:
            year = [MetadataFilter("year", {"2024"})]
            not_built = "Tags for 'year' are not built; call rebuild_tags()"
            with pytest.raises(SearchStoreError, match=not_built):
                await second.search(Term("galaxy"), filters=year)
            with pytest.raises(SearchStoreError, match=not_built):
                await second.filter_ids(filters=year)
            with pytest.raises(SearchStoreError, match=not_built):
                await second.facet_counts(["year"])
            assert await second.filter_ids(filters=[MetadataFilter("categories", {"GA"})]) == frozenset({"r1"})
            await second.index([document("r2", categories=["CO"], year="2025")])
            await second.rebuild_tags()
            assert await second.facet_counts(["year"]) == {"year": (("2024", 1), ("2025", 1))}
            assert raw(path, "SELECT value FROM index_settings") == [('["categories", "year"]',)]

    @pytest.mark.asyncio
    async def test_a_narrowed_key_set_hides_dropped_tags_until_rebuild_removes_them(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("categories", "year")) as first:
            await first.index([document("r1", categories=["GA"], year="2024")])
        async with opened(path, facet_keys=("categories",)) as second:
            tags = raw(path, "SELECT key, value FROM document_tags ORDER BY key")
            assert tags == [("categories", "GA"), ("year", "2024")]
            with pytest.raises(ValueError, match="'year' is not a facet key"):
                await second.filter_ids(filters=[MetadataFilter("year", {"2024"})])
            await second.rebuild_tags()
            assert raw(path, "SELECT key, value FROM document_tags") == [("categories", "GA")]
            assert raw(path, "SELECT value FROM index_settings") == [('["categories"]',)]

    @pytest.mark.asyncio
    async def test_documents_without_recorded_facet_keys_are_not_trusted(self, tmp_path):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("year",)) as first:
            await first.index([document("r1", year="2024")])
        raw(path, "DELETE FROM index_settings")
        async with opened(path, facet_keys=("year",)) as second:
            with pytest.raises(SearchStoreError, match="Tags for 'year' are not built"):
                await second.facet_counts(["year"])
            assert raw(path, "SELECT COUNT(*) FROM index_settings") == [(0,)]
            await second.index([document("r2", year="2025")])
            assert raw(path, "SELECT value FROM document_tags ORDER BY value") == [("2024",), ("2025",)]
            with pytest.raises(SearchStoreError, match="Tags for 'year' are not built"):
                await second.filter_ids(filters=[MetadataFilter("year", {"2025"})])
            await second.rebuild_tags()
            assert await second.facet_counts(["year"]) == {"year": (("2024", 1), ("2025", 1))}

    @pytest.mark.parametrize("value", ["not json", "[1]", '{"year": true}'])
    @pytest.mark.asyncio
    async def test_unreadable_recorded_facet_keys_raise(self, tmp_path, value):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("year",)) as store:
            await store.index([document("r1", year="2024")])
            raw(path, "UPDATE index_settings SET value = ?", (value,))
            with pytest.raises(SearchStoreError, match="recorded facet keys are unreadable"):
                await store.facet_counts(["year"])

    @pytest.mark.parametrize("value", ["not json", "[]"])
    @pytest.mark.asyncio
    async def test_stored_metadata_that_is_not_a_json_object_raises(self, tmp_path, value):
        path = tmp_path / "search.db"
        async with opened(path, facet_keys=("year",)) as store:
            await store.index([document("r1", year="2024")])
            raw(path, "UPDATE documents SET metadata = ?", (value,))
            with pytest.raises(SearchStoreError, match="metadata is not a JSON object"):
                await store.get_documents(["r1"])
            with pytest.raises(SearchStoreError, match="metadata is not a JSON object"):
                await store.search(Term("galaxy"))
            with pytest.raises(SearchStoreError, match="metadata is not a JSON object"):
                await store.rebuild_tags()


class TestLifetime:
    @pytest.mark.asyncio
    async def test_a_cancelled_write_keeps_the_connection_until_its_thread_finishes(self, tmp_path, statement_gate):
        gate = statement_gate(blocked_prefix="INSERT INTO documents (", observed_prefix="SELECT COUNT(*)")
        store = AsyncSqliteFts5Store(tmp_path / "search.db")
        try:
            write = asyncio.create_task(store.index([document("r1")]))
            await asyncio.to_thread(gate.blocked.wait, 5)
            write.cancel()
            count = asyncio.create_task(store.count())
            count_overlapped = await asyncio.to_thread(gate.observed.wait, 0.5)
            gate.release.set()
            await asyncio.to_thread(gate.finished.wait, 5)
            with pytest.raises(asyncio.CancelledError):
                await write
            assert not count_overlapped
            assert await count == 1
            assert gate.events == ["first-start", "first-end", "second-start"]
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_aclose_is_not_terminal(self, tmp_path):
        store = AsyncSqliteFts5Store(tmp_path / "search.db")
        await store.index([document("r1")])
        await store.aclose()
        assert await store.count() == 1
        await store.aclose()

    @pytest.mark.asyncio
    async def test_the_pipeline_closes_a_store_listed_in_closeables(self, tmp_path, mocker):
        path = tmp_path / "search.db"
        store = AsyncSqliteFts5Store(path)
        aclose = mocker.spy(store, "aclose")
        pipeline = AsyncETLPipeline(
            extractor=mocker.Mock(spec=AsyncExtractor),
            relevance_filter=mocker.Mock(spec=AsyncRelevanceFilter),
            entity_extractor=mocker.Mock(spec=AsyncEntityExtractor),
            exporter=mocker.Mock(spec=AsyncExporter),
            state_manager=mocker.Mock(spec=AsyncStateManager),
            destination="out.csv",
            closeables=[store],
        )
        async with pipeline:
            await store.index([document("r1")])
        aclose.assert_awaited_once()
        path.rename(tmp_path / "moved.db")
