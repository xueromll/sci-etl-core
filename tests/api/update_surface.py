"""Regenerate ``public_surface.txt`` from the installed package.

Run from the repository root with ``python tests/api/update_surface.py``. A diff
in the snapshot means the public API changed, and the change needs a
CHANGELOG.md entry.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from surface import SNAPSHOT, render_surface


def main() -> None:
    SNAPSHOT.write_text(render_surface(), encoding="utf-8", newline="\n")
    print(f"Wrote {SNAPSHOT}")


if __name__ == "__main__":
    main()
