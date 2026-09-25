"""Record which public names import from a base install, and which extra the others need.

Run with the interpreter of an environment where only the wheel is installed,
from outside the repository so the checkout is not importable::

    cd "$RUNNER_TEMP"
    wheel-env/bin/python "$GITHUB_WORKSPACE/tests/api/import_map.py" "$GITHUB_WORKSPACE/pyproject.toml"

Each name is imported in a fresh interpreter. The map is printed as a
Markdown table, and appended to the GitHub job summary when one is available.
It records the current state and never fails: release-plan §3.4 turns it into
an assertion once the base install shrinks to ``pydantic``.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import tomllib

PACKAGES = (
    "sci_etl_core",
    "sci_etl_core.embeddings",
    "sci_etl_core.exporters",
    "sci_etl_core.extractors",
    "sci_etl_core.llm",
    "sci_etl_core.parsers",
    "sci_etl_core.processors",
    "sci_etl_core.search",
    "sci_etl_core.state",
)
MODULE_DISTRIBUTIONS = {
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "sentence_transformers": "sentence-transformers",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}
PROBE = """
import importlib, json, sys
try:
    getattr(importlib.import_module(sys.argv[1]), sys.argv[2])
except ModuleNotFoundError as error:
    print(json.dumps({"missing": error.name}))
except Exception as error:
    print(json.dumps({"error": f"{type(error).__name__}: {error}"}))
else:
    print(json.dumps({}))
"""


@dataclass(frozen=True)
class Outcome:
    path: str
    missing: str | None
    error: str | None


def public_names() -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = []
    for package in PACKAGES:
        module = importlib.import_module(package)
        names.extend((package, name) for name in sorted(module.__all__))
    return names


def probe(package: str, name: str) -> Outcome:
    completed = subprocess.run(
        [sys.executable, "-c", PROBE, package, name], capture_output=True, text=True, check=False
    )
    result = json.loads(completed.stdout or json.dumps({"error": completed.stderr.strip()[-200:]}))
    return Outcome(f"{package}.{name}", result.get("missing"), result.get("error"))


def normalized(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def extras_by_distribution(pyproject: Path) -> dict[str, list[str]]:
    optional = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    extras: dict[str, list[str]] = {}
    for extra, requirements in optional.items():
        for requirement in requirements:
            extras.setdefault(normalized(requirement), []).append(extra)
    return extras


def extra_for(missing: str, extras: dict[str, list[str]]) -> str:
    top_level = missing.partition(".")[0]
    distribution = MODULE_DISTRIBUTIONS.get(top_level, top_level).lower().replace("_", "-")
    candidates = [extra for extra in extras.get(distribution, []) if extra != "full"]
    return ", ".join(candidates) or "?"


def render(outcomes: list[Outcome], extras: dict[str, list[str]]) -> str:
    importable = sum(outcome.missing is None and outcome.error is None for outcome in outcomes)
    lines = [
        "## Base-install import map",
        "",
        f"{importable} of {len(outcomes)} public names import from a base install.",
        "",
        "| Name | Missing module | Extra |",
        "|------|----------------|-------|",
    ]
    for outcome in outcomes:
        if outcome.missing is not None:
            lines.append(f"| `{outcome.path}` | `{outcome.missing}` | {extra_for(outcome.missing, extras)} |")
        elif outcome.error is not None:
            lines.append(f"| `{outcome.path}` | error: {outcome.error} | ? |")
    return "\n".join(lines) + "\n"


def main() -> None:
    extras = extras_by_distribution(Path(sys.argv[1]))
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda item: probe(*item), public_names()))
    report = render(outcomes, extras)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)


if __name__ == "__main__":
    main()
