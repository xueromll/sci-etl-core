"""Write ``consumer_surface.txt``: every sci-etl-core name a known consumer imports or subclasses.

Run from the repository root, naming each consumer and where its sources are::

    python tests/api/scan_consumers.py sci-etl-cli=../sci-etl-cli udg-catalogue=../udg-catalogue@origin/main

``NAME=PATH`` reads the working tree at ``PATH``; ``NAME=PATH@REF`` reads the
files committed at ``REF`` in the git repository at ``PATH``, so a local clone
that is behind its remote is never scanned by mistake. Fetch first.

The scan walks each Python file with :mod:`ast`, skipping tests and virtual
environments. It records names bound by ``from sci_etl_core... import`` and the
bases of class definitions reached through an imported ``sci_etl_core`` module.
It does not see names reached through other attribute access, ``getattr``,
``importlib``, or strings.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PACKAGE = "sci_etl_core"
OUTPUT = Path(__file__).with_name("consumer_surface.txt")
SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "site-packages",
        "test",
        "tests",
        "venv",
    }
)


@dataclass(frozen=True)
class Consumer:
    name: str
    path: Path
    ref: str | None


def parse_consumer(spec: str) -> Consumer:
    name, separator, location = spec.partition("=")
    if not separator or not name or not location:
        raise argparse.ArgumentTypeError(f"expected NAME=PATH or NAME=PATH@REF, got {spec!r}")
    path, _, ref = location.partition("@")
    return Consumer(name=name, path=Path(path), ref=ref or None)


def is_scanned(relative: PurePosixPath) -> bool:
    if relative.suffix != ".py":
        return False
    if any(part in SKIPPED_DIRECTORIES or part.endswith(".egg-info") for part in relative.parts[:-1]):
        return False
    return not (relative.name.startswith("test_") or relative.name == "conftest.py")


def git(consumer: Consumer, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(consumer.path), *arguments], check=True, capture_output=True
    )
    return completed.stdout.decode("utf-8")


def sources(consumer: Consumer) -> Iterator[tuple[str, str]]:
    if consumer.ref is None:
        for file in sorted(consumer.path.rglob("*.py")):
            relative = PurePosixPath(file.relative_to(consumer.path).as_posix())
            if is_scanned(relative):
                yield str(relative), file.read_text(encoding="utf-8")
        return
    for listed in sorted(git(consumer, "ls-tree", "-r", "--name-only", consumer.ref).splitlines()):
        if is_scanned(PurePosixPath(listed)):
            yield listed, git(consumer, "show", f"{consumer.ref}:{listed}")


def dotted(node: ast.expr) -> list[str] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return parts[::-1]


def is_core(module: str | None) -> bool:
    return module is not None and (module == PACKAGE or module.startswith(f"{PACKAGE}."))


def core_names(source: str, filename: str) -> set[str]:
    tree = ast.parse(source, filename=filename)
    names: set[str] = set()
    module_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and is_core(node.module):
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not is_core(alias.name):
                    continue
                if alias.asname is None:
                    module_aliases[PACKAGE] = PACKAGE
                else:
                    module_aliases[alias.asname] = alias.name
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            parts = dotted(base)
            if parts is None or len(parts) < 2 or parts[0] not in module_aliases:
                continue
            names.add(".".join([module_aliases[parts[0]], *parts[1:]]))
    return names


def scan(consumers: list[Consumer]) -> dict[str, set[str]]:
    users: dict[str, set[str]] = defaultdict(set)
    for consumer in consumers:
        for filename, source in sources(consumer):
            for name in core_names(source, filename):
                users[name].add(consumer.name)
    return users


def render(users: dict[str, set[str]]) -> str:
    return "".join(f"{name}\t{','.join(sorted(users[name]))}\n" for name in sorted(users))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("consumers", nargs="+", type=parse_consumer, metavar="NAME=PATH[@REF]")
    arguments = parser.parse_args(argv)
    OUTPUT.write_text(render(scan(arguments.consumers)), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
