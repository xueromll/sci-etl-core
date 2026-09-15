from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def _loaded_modules(code: str) -> set[str]:
    script = textwrap.dedent(code) + "\nimport sys\nprint('\\n'.join(sys.modules))\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        timeout=120,
        check=True,
    )
    return set(result.stdout.split())


def test_boolean_search_loads_only_the_standard_library():
    baseline = _loaded_modules("")
    loaded = _loaded_modules(
        """
        from sci_etl_core.search import Unicode61Tokenizer, normalize, parse_query
        normalize(parse_query('title:"dwarf galaxy" photometr* -quasar'))
        Unicode61Tokenizer().tokens("Müller's H-alpha")
        """
    )
    added = {name.partition(".")[0] for name in loaded - baseline}
    assert added - set(sys.stdlib_module_names) == {"sci_etl_core"}
