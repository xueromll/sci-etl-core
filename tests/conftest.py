from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import settings

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

settings.register_profile("ci", deadline=None, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


def _install_sqlalchemy_stub() -> None:
    """Register lightweight stub modules so the SQL exporters import offline.

    Keeps the test suite offline-first while still exercising every line of the
    SQL exporters. When the real package is installed the stub is not used.
    """
    try:
        import sqlalchemy  # noqa: F401
    except ModuleNotFoundError:
        base = types.ModuleType("sqlalchemy")
        base.create_engine = lambda *args, **kwargs: None
        ext = types.ModuleType("sqlalchemy.ext")
        asyncio_mod = types.ModuleType("sqlalchemy.ext.asyncio")
        asyncio_mod.create_async_engine = lambda *args, **kwargs: None
        base.ext = ext
        ext.asyncio = asyncio_mod
        sys.modules["sqlalchemy"] = base
        sys.modules["sqlalchemy.ext"] = ext
        sys.modules["sqlalchemy.ext.asyncio"] = asyncio_mod


_install_sqlalchemy_stub()

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
