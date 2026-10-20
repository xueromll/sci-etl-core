from __future__ import annotations

import csv
import sqlite3
from contextlib import closing

import pytest

from sci_etl_core.claims.drafts import ClaimDraft
from sci_etl_core.claims.exporter_async import AsyncClaimStoreExporter
from sci_etl_core.claims.models import Claim, EvidenceSpan, ExtractionStamp
from sci_etl_core.claims.store_memory import InMemoryClaimStore
from sci_etl_core.claims.store_sqlite_async import AsyncSqliteClaimStore
from sci_etl_core.exporters.csv_async import AsyncCsvExporter
from sci_etl_core.exporters.jsonl_async import AsyncJsonlExporter, read_jsonl_export
from sci_etl_core.models import RawRecord
from sci_etl_core.testing import ExporterContract

STAMP = ExtractionStamp(model="m", prompt_hash="p", schema_hash="s", extractor_version="v")


def _claims(record: RawRecord, count: int) -> list[Claim]:
    claims = []
    for index in range(count):
        quote = f"object {index} is described"
        draft = ClaimDraft(
            kind="assertion", subject=f"object {index}", predicate="described_by", object="text", quote=quote
        )
        span = EvidenceSpan(record_id=record.record_id, start=index * 40, end=index * 40 + len(quote), quote=quote)
        claims.append(Claim.from_draft(draft, span=span, stamp=STAMP))
    return claims


def _csv_rows(path, record_id: str) -> list[tuple[str, ...]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [tuple(row) for row in csv.reader(handle) if row[0] == record_id]


def _write_user_version(path, version: int) -> None:
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute(f"PRAGMA user_version = {version}")


class TestAsyncJsonlExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncJsonlExporter(tmp_path / "nested" / "out.jsonl", fsync=False)

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            return read_jsonl_export(tmp_path / "nested" / "out.jsonl").get(record_id, [])

        return read


class TestAsyncCsvExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncCsvExporter(tmp_path / "nested" / "out.csv", ["name", "value"])

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            return _csv_rows(tmp_path / "nested" / "out.csv", record_id)

        return read


class TestAsyncClaimStoreExporterInMemory(ExporterContract):
    @pytest.fixture
    def store(self):
        return InMemoryClaimStore()

    @pytest.fixture
    def make_exporter(self, store):
        return lambda: AsyncClaimStoreExporter(store)

    @pytest.fixture
    def read_exported(self, store):
        async def read(record_id):
            return (await store.claims_for_records([record_id])).get(record_id, [])

        return read

    @pytest.fixture
    def make_entities(self):
        return _claims


class TestAsyncClaimStoreExporterSqlite(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncClaimStoreExporter(AsyncSqliteClaimStore(tmp_path / "claims.db"))

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            store = AsyncSqliteClaimStore(tmp_path / "claims.db")
            claims = await store.claims_for_records([record_id])
            await store.aclose()
            return claims.get(record_id, [])

        return read

    @pytest.fixture
    def make_entities(self):
        return _claims

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        return lambda: _write_user_version(tmp_path / "claims.db", 99)
