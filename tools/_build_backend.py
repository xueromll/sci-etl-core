from __future__ import annotations

import sys
from pathlib import Path

from setuptools import build_meta as _origin

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))


def _generate() -> None:
    import generate_sync

    generate_sync.generate(_ROOT / "src")


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _generate()
    return _origin.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    _generate()
    return _origin.build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    _generate()
    return _origin.build_editable(wheel_directory, config_settings, metadata_directory)


get_requires_for_build_wheel = _origin.get_requires_for_build_wheel
get_requires_for_build_sdist = _origin.get_requires_for_build_sdist
get_requires_for_build_editable = _origin.get_requires_for_build_editable
prepare_metadata_for_build_wheel = _origin.prepare_metadata_for_build_wheel
prepare_metadata_for_build_editable = _origin.prepare_metadata_for_build_editable
