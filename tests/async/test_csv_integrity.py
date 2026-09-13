from __future__ import annotations

import pandas as pd
import pytest

from sci_etl_core.exporters.csv_async import AsyncCsvUpsertExporter
from sci_etl_core.processors.normalization import DefaultKeyNormalizer

pytestmark = pytest.mark.filterwarnings("error::FutureWarning")


def _exporter() -> AsyncCsvUpsertExporter:
    return AsyncCsvUpsertExporter("name", ["ra", "dec"], DefaultKeyNormalizer())


class TestUnreadableExistingFile:
    @pytest.mark.parametrize(
        "existing",
        [
            "name,ra,dec\nCafé Object,1.0,2.0\nOld Row,3.0,4.0\n".encode("cp1252"),
            b'name,ra,dec\nOld Row,1.0,2.0\n"unterminated,3,4\n',
        ],
        ids=["foreign-encoding", "malformed-row"],
    )
    @pytest.mark.asyncio
    async def test_failed_read_never_lets_a_later_export_overwrite_the_file(self, tmp_path, existing):
        dest = tmp_path / "out.csv"
        dest.write_bytes(existing)
        exporter = _exporter()
        for batch in ([{"name": "New A", "ra": 1.0}], [{"name": "New B", "ra": 2.0}]):
            with pytest.raises((UnicodeDecodeError, pd.errors.ParserError)):
                await exporter.export(batch, str(dest))
        assert dest.read_bytes() == existing

    @pytest.mark.asyncio
    async def test_export_proceeds_once_the_file_is_readable(self, tmp_path):
        dest = tmp_path / "out.csv"
        dest.write_bytes("name,ra,dec\nCafé,1.0,2.0\n".encode("cp1252"))
        exporter = _exporter()
        with pytest.raises(UnicodeDecodeError):
            await exporter.export([{"name": "New", "ra": 5.0}], str(dest))
        dest.write_text("name,ra,dec\nCafé,1.0,2.0\n", encoding="utf-8")
        await exporter.export([{"name": "New", "ra": 5.0}], str(dest))
        assert pd.read_csv(dest)["name"].tolist() == ["Café", "New"]


class TestDestinations:
    @pytest.mark.asyncio
    async def test_each_destination_keeps_only_its_own_rows(self, tmp_path):
        first, second = tmp_path / "a.csv", tmp_path / "b.csv"
        second.write_text("name,ra,dec\nExisting,9.0,9.0\n", encoding="utf-8")
        exporter = _exporter()
        await exporter.export([{"name": "Only In A", "ra": 1.0}], str(first))
        await exporter.export([{"name": "Only In B", "ra": 2.0}], str(second))
        assert pd.read_csv(first)["name"].tolist() == ["Only In A"]
        assert pd.read_csv(second)["name"].tolist() == ["Existing", "Only In B"]


class TestFrameShapes:
    @pytest.mark.asyncio
    async def test_header_only_file_is_extended(self, tmp_path):
        dest = tmp_path / "out.csv"
        dest.write_text("name,ra,dec\n", encoding="utf-8")
        await _exporter().export([{"name": "A", "ra": 1.0}], str(dest))
        assert pd.read_csv(dest)["name"].tolist() == ["A"]

    @pytest.mark.asyncio
    async def test_file_without_the_key_column_gains_it(self, tmp_path):
        dest = tmp_path / "out.csv"
        dest.write_text("ra\n1.0\n", encoding="utf-8")
        await _exporter().export([{"name": "A", "dec": 2.0}], str(dest))
        frame = pd.read_csv(dest)
        assert set(frame.columns) == {"name", "ra", "dec"}
        assert len(frame) == 2

    @pytest.mark.asyncio
    async def test_items_that_cannot_form_a_row_are_skipped(self, tmp_path):
        dest = tmp_path / "out.csv"
        items = ["not a dict", {"name": ["a", "b"], "ra": 1.0}, {"name": {"x": 1}}, {"name": "Kept", "ra": 2.0}]
        await _exporter().export(items, str(dest))
        assert pd.read_csv(dest)["name"].tolist() == ["Kept"]

    @pytest.mark.asyncio
    async def test_rows_with_all_missing_values_are_written(self, tmp_path):
        dest = tmp_path / "out.csv"
        await _exporter().export([{"name": "A"}, {"name": "B", "dec": None}], str(dest))
        await _exporter().export([{"name": "C"}], str(dest))
        assert pd.read_csv(dest)["name"].tolist() == ["A", "B", "C"]
