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


class TestCsvFormulaEscaping:
    @pytest.mark.asyncio
    async def test_formula_like_keys_are_escaped_in_the_file(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        records = [
            {"name": '=HYPERLINK("http://x")', "ra": 1.0},
            {"name": "@cmd", "ra": 2.0},
            {"name": "Plain", "ra": 3.0},
        ]
        await exporter.export(records, str(dest))
        names = pd.read_csv(dest, dtype={"name": str})["name"].tolist()
        assert names == ["'=HYPERLINK(\"http://x\")", "'@cmd", "Plain"]

    @pytest.mark.asyncio
    async def test_escaped_keys_round_trip_through_a_reload(self, tmp_path):
        dest = tmp_path / "out.csv"
        keys = ["=1+1", "'quoted", "-negative", "+plus", "plain"]
        await AsyncCsvUpsertExporter("name", ["ra", "dec"], DefaultKeyNormalizer()).export(
            [{"name": key, "ra": 1.0} for key in keys], str(dest)
        )
        reloaded = AsyncCsvUpsertExporter("name", ["ra", "dec"], DefaultKeyNormalizer())
        await reloaded.export([{"name": key, "dec": 2.0} for key in keys], str(dest))
        frame = pd.read_csv(dest)
        assert len(frame) == len(keys)
        assert frame["dec"].tolist() == [2.0] * len(keys)
        assert reloaded._frame["name"].tolist() == keys

    @pytest.mark.asyncio
    async def test_non_text_keys_are_left_unchanged(self, exporter, tmp_path):
        dest = tmp_path / "out.csv"
        pd.DataFrame({"name": ["", "Alpha"], "ra": [1.0, 2.0]}).to_csv(dest, index=False)
        await exporter.export([{"name": 7, "ra": 3.0}], str(dest))
        written = pd.read_csv(dest, dtype={"name": str}, keep_default_na=False)
        assert written["name"].tolist() == ["", "Alpha", "7"]

    @pytest.mark.asyncio
    async def test_escaping_can_be_disabled(self, tmp_path):
        dest = tmp_path / "out.csv"
        exporter = AsyncCsvUpsertExporter(
            "name", ["ra"], DefaultKeyNormalizer(), escape_formulas=False
        )
        await exporter.export([{"name": "=1+1", "ra": 1.0}], str(dest))
        assert pd.read_csv(dest, dtype={"name": str})["name"].tolist() == ["=1+1"]
