from __future__ import annotations

import csv
import dataclasses

import pytest
from pydantic import BaseModel

from sci_etl_core.exceptions import ExportError
from sci_etl_core.exporters._entities import entity_to_dict
from sci_etl_core.exporters.csv_async import AsyncCsvExporter
from sci_etl_core.models import RawRecord


def record(record_id: str) -> RawRecord:
    return RawRecord(record_id=record_id, title="t", abstract="a")


def read(path) -> list[list[str]]:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


async def run(path, writes, columns=("name", "ra")) -> AsyncCsvExporter:
    exporter = AsyncCsvExporter(path, list(columns))
    await exporter.open()
    for record_id, entities in writes:
        await exporter.write(record(record_id), entities)
    await exporter.flush()
    await exporter.aclose()
    return exporter


class Galaxy(BaseModel):
    name: str
    ra: float


@dataclasses.dataclass
class Point:
    name: str
    ra: float


class TestLongFormat:
    @pytest.mark.asyncio
    async def test_one_row_per_entity_tagged_with_its_record(self, tmp_path):
        path = tmp_path / "out.csv"
        await run(path, [("p1", [{"name": "DF2", "ra": 40.4}, {"name": "DF4", "ra": 40.1}]), ("p2", [{"name": "DF2"}])])

        assert read(path) == [
            ["record_id", "name", "ra", "extra"],
            ["p1", "DF2", "40.4", ""],
            ["p1", "DF4", "40.1", ""],
            ["p2", "DF2", "", ""],
        ]

    @pytest.mark.asyncio
    async def test_conflicting_values_from_two_papers_both_survive(self, tmp_path):
        path = tmp_path / "out.csv"
        await run(path, [("p1", [{"name": "DF2", "ra": 40.44}]), ("p2", [{"name": "DF2", "ra": "40h 26m"}])])

        assert [row[2] for row in read(path)[1:]] == ["40.44", "40h 26m"]

    @pytest.mark.asyncio
    async def test_values_are_written_unchanged_and_other_keys_go_to_extra(self, tmp_path):
        path = tmp_path / "out.csv"
        entity = {"name": "A", "ra": "3.2 ± 0.4", "flag": True, "tags": ["x"], "size": 1}
        await run(path, [("p1", [entity])])

        assert read(path)[1] == ["p1", "A", "3.2 ± 0.4", '{"flag": true, "size": 1, "tags": ["x"]}']

    @pytest.mark.asyncio
    async def test_scalars_and_structures_are_rendered_as_text(self, tmp_path):
        path = tmp_path / "out.csv"
        await run(
            path,
            [("p1", [{"a": True, "b": False, "c": 2, "d": 0.1, "e": {"k": 1}}])],
            columns=("a", "b", "c", "d", "e"),
        )

        assert read(path)[1] == ["p1", "true", "false", "2", "0.1", '{"k": 1}', ""]

    @pytest.mark.asyncio
    async def test_models_dataclasses_and_dicts_are_accepted(self, tmp_path):
        path = tmp_path / "out.csv"
        await run(path, [("p1", [Galaxy(name="A", ra=1.0), Point(name="B", ra=2.0), {"name": "C", "ra": 3.0}])])

        assert [row[1:3] for row in read(path)[1:]] == [["A", "1.0"], ["B", "2.0"], ["C", "3.0"]]

    @pytest.mark.asyncio
    async def test_an_unsupported_entity_type_fails_the_write(self, tmp_path):
        exporter = AsyncCsvExporter(tmp_path / "out.csv", ["name"])
        await exporter.open()

        with pytest.raises(TypeError, match="Cannot export an entity of type int"):
            await exporter.write(record("p1"), [3])


class TestReplacement:
    @pytest.mark.asyncio
    async def test_writing_a_record_again_replaces_its_rows(self, tmp_path):
        path = tmp_path / "out.csv"
        await run(path, [("p1", [{"name": "A"}, {"name": "B"}]), ("p2", [{"name": "C"}])])
        await run(path, [("p1", [{"name": "Z"}])])

        assert [row[:2] for row in read(path)[1:]] == [["p1", "Z"], ["p2", "C"]]

    @pytest.mark.asyncio
    async def test_a_destination_in_a_new_folder_is_created(self, tmp_path):
        path = tmp_path / "out" / "nested" / "results.csv"
        await run(path, [("p1", [{"name": "A"}])])

        assert read(path)[1][:2] == ["p1", "A"]

    @pytest.mark.asyncio
    async def test_a_record_written_with_no_entities_loses_its_rows(self, tmp_path):
        path = tmp_path / "out.csv"
        await run(path, [("p1", [{"name": "A"}]), ("p2", [{"name": "B"}])])
        await run(path, [("p1", [])])

        assert [row[0] for row in read(path)[1:]] == ["p2"]


class TestJournal:
    @pytest.mark.asyncio
    async def test_the_csv_is_rendered_only_when_the_run_closes(self, tmp_path):
        path = tmp_path / "out.csv"
        exporter = AsyncCsvExporter(path, ["name"])
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "A"}])
        await exporter.flush()

        assert not path.exists()
        assert exporter.journal_path.read_text(encoding="utf-8").count("\n") == 1

        await exporter.aclose()
        assert read(path)[1] == ["p1", "A", ""]
        assert not exporter.journal_path.exists()

    @pytest.mark.asyncio
    async def test_a_torn_last_journal_line_is_ignored(self, tmp_path):
        path = tmp_path / "out.csv"
        exporter = AsyncCsvExporter(path, ["name"])
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "A"}])
        await exporter.flush()
        with exporter.journal_path.open("a", encoding="utf-8") as journal:
            journal.write('{"record_id": "p2", "rows": [["p2", "B"')

        await run(path, [], columns=("name",))

        assert read(path)[1:] == [["p1", "A", ""]]

    @pytest.mark.asyncio
    async def test_a_journal_entry_that_is_not_one_fails_the_open(self, tmp_path):
        exporter = AsyncCsvExporter(tmp_path / "out.csv", ["name"])
        exporter.journal_path.write_text("not json\n", encoding="utf-8")

        with pytest.raises(ExportError, match=r"out\.csv\.journal:1 is not a journal entry"):
            await exporter.open()

    @pytest.mark.asyncio
    async def test_a_failed_flush_keeps_the_records_queued(self, tmp_path, mocker):
        exporter = AsyncCsvExporter(tmp_path / "out.csv", ["name"])
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "A"}])
        mocker.patch("sci_etl_core.exporters.csv_async.os.fsync", side_effect=[OSError("disk full"), None])

        with pytest.raises(ExportError, match="Cannot append"):
            await exporter.flush()
        await exporter.flush()

        assert '"p1"' in exporter.journal_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_a_failed_render_keeps_the_journal_for_the_next_open(self, tmp_path, mocker):
        path = tmp_path / "out.csv"
        exporter = AsyncCsvExporter(path, ["name"])
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "A"}])
        mocker.patch("sci_etl_core.exporters.csv_async.atomic_write_text", side_effect=OSError("locked"))

        with pytest.raises(ExportError, match="Cannot write"):
            await exporter.aclose()
        mocker.stopall()

        assert exporter.journal_path.exists()
        await run(path, [], columns=("name",))
        assert read(path)[1:] == [["p1", "A", ""]]

    @pytest.mark.asyncio
    async def test_open_twice_and_close_without_open_are_harmless(self, tmp_path):
        exporter = AsyncCsvExporter(tmp_path / "out.csv", ["name"])
        await exporter.aclose()
        await exporter.open()
        await exporter.open()
        await exporter.aclose()

        assert read(tmp_path / "out.csv") == [["record_id", "name", "extra"]]


class TestExistingFile:
    @pytest.mark.asyncio
    async def test_a_different_header_fails_the_open_and_leaves_the_file(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_text("name,ra,dec\nA,1,2\n", encoding="utf-8")

        with pytest.raises(ExportError, match="has the header"):
            await AsyncCsvExporter(path, ["name", "ra"]).open()
        assert path.read_text(encoding="utf-8") == "name,ra,dec\nA,1,2\n"

    @pytest.mark.asyncio
    async def test_a_row_with_the_wrong_number_of_cells_fails_the_open(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_text("record_id,name,extra\np1,A\n", encoding="utf-8")

        with pytest.raises(ExportError, match=r"out\.csv:2 has 2 cells, not 3"):
            await AsyncCsvExporter(path, ["name"]).open()

    @pytest.mark.asyncio
    async def test_a_file_in_a_foreign_encoding_fails_the_open(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_bytes("record_id,name,extra\np1,Café,\n".encode("cp1252"))

        with pytest.raises(UnicodeDecodeError):
            await AsyncCsvExporter(path, ["name"]).open()
        assert path.read_bytes() == "record_id,name,extra\np1,Café,\n".encode("cp1252")

    @pytest.mark.asyncio
    async def test_an_unreadable_file_is_an_export_error(self, tmp_path, mocker):
        path = tmp_path / "out.csv"
        path.write_text("record_id,name,extra\n", encoding="utf-8")
        mocker.patch.object(AsyncCsvExporter, "_read_table", side_effect=PermissionError("locked"))

        with pytest.raises(ExportError, match="Cannot read"):
            await AsyncCsvExporter(path, ["name"]).open()

    @pytest.mark.asyncio
    async def test_a_destination_that_cannot_be_written_fails_the_replay(self, tmp_path):
        path = tmp_path / "out.csv"
        path.mkdir()
        exporter = AsyncCsvExporter(path, ["name"])
        exporter.journal_path.write_text("", encoding="utf-8")

        with pytest.raises(ExportError, match="Cannot write"):
            await exporter.open()

    @pytest.mark.asyncio
    async def test_an_empty_file_starts_an_empty_table(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_text("", encoding="utf-8")

        await run(path, [("p1", [{"name": "A"}])], columns=("name",))

        assert read(path)[1:] == [["p1", "A", ""]]


class TestFormulaEscaping:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["=cmd()", "+1", "-1", "@SUM", "\tx", "'quoted"])
    async def test_formula_cells_are_escaped_on_disk_and_restored_on_reload(self, tmp_path, value):
        path = tmp_path / "out.csv"
        await run(path, [("=p1", [{"name": value}])], columns=("name",))

        assert read(path)[1][:2] == ["'=p1", "'" + value]
        await run(path, [("p2", [{"name": "B"}])], columns=("name",))
        assert read(path)[1][:2] == ["'=p1", "'" + value]

    @pytest.mark.asyncio
    async def test_escaping_can_be_turned_off(self, tmp_path):
        path = tmp_path / "out.csv"
        exporter = AsyncCsvExporter(path, ["name"], escape_formulas=False)
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "=1+1"}])
        await exporter.aclose()
        await exporter.open()
        await exporter.aclose()

        assert read(path)[1] == ["p1", "=1+1", ""]


class TestConstruction:
    @pytest.mark.parametrize(
        ("columns", "message"),
        [
            ([], "at least one"),
            (["a", "a"], "must not repeat"),
            (["record_id"], "must not include"),
            (["extra"], "must not include"),
        ],
    )
    def test_invalid_columns_are_rejected(self, tmp_path, columns, message):
        with pytest.raises(ValueError, match=message):
            AsyncCsvExporter(tmp_path / "out.csv", columns)

    def test_properties(self, tmp_path):
        exporter = AsyncCsvExporter(tmp_path / "out.csv", ["name"])

        assert exporter.path == tmp_path / "out.csv"
        assert exporter.journal_path == tmp_path / "out.csv.journal"
        assert exporter.header == ("record_id", "name", "extra")
        assert exporter.durable_writes is False


class TestEntityToDict:
    def test_an_object_with_to_row_gives_its_mapping(self):
        class Row:
            def to_row(self):
                return {"a": 1}

        assert entity_to_dict(Row()) == {"a": 1}

    def test_a_dataclass_type_is_not_an_entity(self):
        with pytest.raises(TypeError):
            entity_to_dict(Point)
