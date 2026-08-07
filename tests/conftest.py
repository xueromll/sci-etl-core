from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sci_etl_core.models import RawRecord


@pytest.fixture
def raw_record() -> RawRecord:
    return RawRecord(record_id="2401.00001", title="A Title", abstract="An abstract.")


@pytest.fixture
def make_record():
    def _make(record_id: str = "id", title: str = "t", abstract: str = "a", **metadata) -> RawRecord:
        return RawRecord(record_id=record_id, title=title, abstract=abstract, metadata=metadata)

    return _make


@pytest.fixture
def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": ["Alpha", "alpha", "Beta", "Gamma"],
            "ra": [10.0, 10.0, 200.0, None],
            "dec": [-5.0, -5.0, 40.0, 12.0],
            "value": [1.0, None, 3.0, 4.0],
        }
    )
