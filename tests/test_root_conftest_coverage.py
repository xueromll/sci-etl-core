from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

from sci_etl_core.models import RawRecord


def test_raw_record_fixture(raw_record: RawRecord) -> None:
    assert raw_record.record_id == "2401.00001"
    assert raw_record.title == "A Title"
    assert raw_record.abstract == "An abstract."


def test_make_record_defaults(make_record) -> None:
    record = make_record()
    assert isinstance(record, RawRecord)
    assert (record.record_id, record.title, record.abstract) == ("id", "t", "a")
    assert record.metadata == {}


def test_make_record_overrides(make_record) -> None:
    record = make_record(record_id="x", title="T", abstract="A", source="unit", year=2024)
    assert record.record_id == "x"
    assert record.metadata == {"source": "unit", "year": 2024}


def test_sample_frame_fixture(sample_frame: pd.DataFrame) -> None:
    assert list(sample_frame.columns) == ["name", "ra", "dec", "value"]
    assert len(sample_frame) == 4
    assert sample_frame["value"].isna().sum() == 1


def _exec_conftest(path: Path) -> object:
    spec = importlib.util.spec_from_file_location(f"_reexec_{path.parent.name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conftest_prepends_src_to_path() -> None:
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    src = str(Path(__file__).resolve().parents[1] / "src")
    original = list(sys.path)
    try:
        sys.path[:] = [entry for entry in sys.path if entry != src]
        _exec_conftest(conftest_path)
        assert src in sys.path
    finally:
        sys.path[:] = original
