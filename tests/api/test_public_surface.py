from __future__ import annotations

import difflib

import pytest
from surface import SNAPSHOT, consumer_names, render_surface, resolve, stable_objects


def test_public_surface_matches_the_snapshot():
    expected = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    actual = render_surface().splitlines()
    diff = "\n".join(difflib.unified_diff(expected, actual, "public_surface.txt", "current", lineterm=""))
    assert not diff, (
        "The stable public API changed. If the change is intended, run "
        "`python tests/api/update_surface.py` and record it in CHANGELOG.md.\n" + diff
    )


def test_stable_names_are_unique():
    paths = [path for path, _ in stable_objects()]
    assert len(paths) == len(set(paths))


@pytest.mark.parametrize("name", consumer_names())
def test_every_name_a_consumer_uses_is_stable(name):
    stable = {id(value) for _, value in stable_objects()}
    assert id(resolve(name)) in stable, f"{name} is used by a known consumer, so it must be in surface.STABLE"
