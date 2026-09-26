from __future__ import annotations

import json

import pytest

from sci_etl_core.exceptions import ExportError
from sci_etl_core.exporters.jsonl_async import AsyncJsonlExporter, read_jsonl_export
from sci_etl_core.models import RawRecord


def record(record_id: str) -> RawRecord:
    return RawRecord(record_id=record_id, title=f"title {record_id}", abstract="a", source_url=f"https://x/{record_id}")


class TestAsyncJsonlExporter:
    @pytest.mark.asyncio
    async def test_each_record_is_one_line_with_its_provenance_and_entities(self, tmp_path):
        path = tmp_path / "nested" / "out.jsonl"
        exporter = AsyncJsonlExporter(path)
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "DF2"}])
        await exporter.write(record("p2"), [])
        await exporter.flush()
        await exporter.aclose()

        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert lines == [
            {"record_id": "p1", "title": "title p1", "source_url": "https://x/p1", "entities": [{"name": "DF2"}]},
            {"record_id": "p2", "title": "title p2", "source_url": "https://x/p2", "entities": []},
        ]
        assert exporter.path == path
        assert exporter.durable_writes is False

    @pytest.mark.asyncio
    async def test_nothing_reaches_the_file_before_a_flush(self, tmp_path):
        exporter = AsyncJsonlExporter(tmp_path / "out.jsonl", fsync=False)
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "A"}])

        assert (tmp_path / "out.jsonl").read_text(encoding="utf-8") == ""
        await exporter.aclose()
        assert read_jsonl_export(tmp_path / "out.jsonl") == {"p1": [{"name": "A"}]}

    @pytest.mark.asyncio
    async def test_the_last_line_for_a_record_wins_including_an_empty_one(self, tmp_path):
        path = tmp_path / "out.jsonl"
        for entities in ([{"name": "A"}], [{"name": "B"}], []):
            exporter = AsyncJsonlExporter(path)
            await exporter.open()
            await exporter.write(record("p1"), entities)
            await exporter.aclose()

        assert read_jsonl_export(path) == {"p1": []}

    @pytest.mark.asyncio
    async def test_a_flush_without_open_opens_the_file(self, tmp_path):
        exporter = AsyncJsonlExporter(tmp_path / "out.jsonl")
        await exporter.write(record("p1"), [])
        await exporter.flush()
        await exporter.flush()
        await exporter.aclose()
        await exporter.aclose()

        assert list(read_jsonl_export(tmp_path / "out.jsonl")) == ["p1"]

    @pytest.mark.asyncio
    async def test_a_failed_append_is_truncated_back_and_stays_queued(self, tmp_path, mocker):
        path = tmp_path / "out.jsonl"
        exporter = AsyncJsonlExporter(path)
        await exporter.open()
        await exporter.write(record("p1"), [{"name": "A"}])
        mocker.patch("sci_etl_core.exporters.jsonl_async.os.fsync", side_effect=[OSError("disk full"), None])

        with pytest.raises(ExportError, match="Cannot append"):
            await exporter.flush()
        assert path.read_text(encoding="utf-8") == ""

        await exporter.flush()
        await exporter.aclose()
        assert read_jsonl_export(path) == {"p1": [{"name": "A"}]}

    @pytest.mark.asyncio
    async def test_a_truncation_fault_still_reports_the_append_fault(self, tmp_path, mocker):
        exporter = AsyncJsonlExporter(tmp_path / "out.jsonl")
        await exporter.open()
        await exporter.write(record("p1"), [])
        mocker.patch("sci_etl_core.exporters.jsonl_async.os.fsync", side_effect=OSError("disk full"))
        handle = exporter._handle
        mocker.patch.object(handle, "truncate", side_effect=OSError("still full"))

        with pytest.raises(ExportError, match="disk full"):
            await exporter.flush()
        mocker.stopall()
        await exporter.aclose()

    @pytest.mark.asyncio
    async def test_a_path_that_cannot_be_opened_is_an_export_error(self, tmp_path):
        (tmp_path / "dir").mkdir()

        with pytest.raises(ExportError, match="Cannot open"):
            await AsyncJsonlExporter(tmp_path / "dir").open()


class TestReadJsonlExport:
    def test_blank_lines_are_skipped(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_text('{"record_id": "p1", "entities": []}\n\n', encoding="utf-8")

        assert read_jsonl_export(path) == {"p1": []}

    @pytest.mark.parametrize("line", ["not json", '{"entities": []}', "[]"])
    def test_a_line_that_is_not_a_record_line_is_an_error(self, tmp_path, line):
        path = tmp_path / "out.jsonl"
        path.write_text(line + "\n", encoding="utf-8")

        with pytest.raises(ExportError, match=r"out\.jsonl:1"):
            read_jsonl_export(path)
