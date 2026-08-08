from __future__ import annotations

import pandas as pd
import pytest

from sci_etl_core.exporters.csv_async import AsyncCsvUpsertExporter
from sci_etl_core.processors.normalization import DefaultKeyNormalizer


@pytest.fixture
def exporter() -> AsyncCsvUpsertExporter:
    return AsyncCsvUpsertExporter(
        key_column="name",
        value_columns=["ra", "dec"],
        normalizer=DefaultKeyNormalizer(),
        numeric_clip={"dec": (-90.0, 90.0)},
    )


class TestAsyncCsvUpsertExporter:
    @pytest.mark.asyncio
    async def test_creates_file_with_new_records(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        await exporter.export([{"name": "Alpha", "ra": 10.0, "dec": 5.0}], str(dest))
        frame = pd.read_csv(dest)
        assert frame.loc[0, "name"] == "Alpha"
        assert frame.loc[0, "ra"] == 10.0

    @pytest.mark.asyncio
    async def test_upsert_fills_missing_without_overwriting(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        await exporter.export([{"name": "Alpha", "ra": 10.0}], str(dest))
        await exporter.export([{"name": "alpha", "ra": 99.0, "dec": 5.0}], str(dest))
        frame = pd.read_csv(dest)
        assert len(frame) == 1
        assert frame.loc[0, "ra"] == 10.0
        assert frame.loc[0, "dec"] == 5.0

    @pytest.mark.asyncio
    async def test_distinct_keys_create_separate_rows(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        await exporter.export([{"name": "Alpha", "ra": 1.0}, {"name": "Beta", "ra": 2.0}], str(dest))
        assert len(pd.read_csv(dest)) == 2

    @pytest.mark.asyncio
    async def test_numeric_values_are_clipped(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        await exporter.export([{"name": "Alpha", "dec": 999.0}], str(dest))
        assert pd.read_csv(dest).loc[0, "dec"] == 90.0

    @pytest.mark.asyncio
    async def test_non_numeric_becomes_null(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        await exporter.export([{"name": "Alpha", "ra": "not-a-number"}], str(dest))
        assert pd.isna(pd.read_csv(dest).loc[0, "ra"])

    @pytest.mark.asyncio
    async def test_records_without_key_are_skipped(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        await exporter.export([{"ra": 10.0}, {"name": "Alpha", "ra": 1.0}], str(dest))
        assert len(pd.read_csv(dest)) == 1

    @pytest.mark.asyncio
    async def test_empty_payload_is_noop(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        await exporter.export([], str(dest))
        assert not dest.exists()

    @pytest.mark.asyncio
    async def test_missing_value_column_is_added(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        pd.DataFrame({"name": ["Alpha"], "ra": [1.0]}).to_csv(dest, index=False)
        await exporter.export([{"name": "Beta", "ra": 2.0, "dec": 3.0}], str(dest))
        assert "dec" in pd.read_csv(dest).columns
