from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _exec_conftest(path: Path) -> object:
    spec = importlib.util.spec_from_file_location(f"_reexec_{path.parent.name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_async_conftest_prepends_src_to_path() -> None:
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    src = str(Path(__file__).resolve().parents[2] / "src")
    original = list(sys.path)
    try:
        sys.path[:] = [entry for entry in sys.path if entry != src]
        _exec_conftest(conftest_path)
        assert src in sys.path
    finally:
        sys.path[:] = original
