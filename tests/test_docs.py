from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src"
PACKAGE = "sci_etl_core"

_PYTHON_BLOCK = re.compile(
    r"^(?P<indent>[ \t]*)```python[^\n]*\n(?P<body>.*?)^(?P=indent)```",
    re.MULTILINE | re.DOTALL,
)
_REFERENCE_ENTRY = re.compile(r"^::: (?P<module>sci_etl_core[\w.]*)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Example:
    path: Path
    line: int
    source: str

    @property
    def label(self) -> str:
        return f"{self.path.relative_to(ROOT).as_posix()}:{self.line}"


def _examples() -> list[Example]:
    pages = sorted(DOCS.rglob("*.md")) + [ROOT / "README.md"]
    examples: list[Example] = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for match in _PYTHON_BLOCK.finditer(text):
            indent = len(match["indent"])
            body = "".join(line[indent:] for line in match["body"].splitlines(keepends=True))
            examples.append(Example(page, text.count("\n", 0, match.start()) + 1, body))
    return examples


EXAMPLES = _examples()


def _parse(example: Example) -> ast.Module:
    return ast.parse(example.source, filename=example.label)


def _imported_objects(tree: ast.Module) -> dict[str, object]:
    objects: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == PACKAGE:
            module = importlib.import_module(node.module)
            for alias in node.names:
                objects[alias.asname or alias.name] = getattr(module, alias.name)
    return objects


def _is_checkable(call: ast.Call) -> bool:
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return False
    if any(keyword.arg is None for keyword in call.keywords):
        return False
    return not any(isinstance(arg, ast.Constant) and arg.value is Ellipsis for arg in call.args)


def test_examples_were_found():
    assert len(EXAMPLES) > 20


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.label)
def test_example_compiles(example: Example):
    compile(example.source, example.label, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.label)
def test_example_imports_exist(example: Example):
    for node in ast.walk(_parse(example)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == PACKAGE:
            module = importlib.import_module(node.module)
            missing = [alias.name for alias in node.names if not hasattr(module, alias.name)]
            assert not missing, f"{example.label} imports {missing} from {node.module}, which doesn't define them"


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.label)
def test_example_calls_match_signatures(example: Example):
    tree = _parse(example)
    objects = _imported_objects(tree)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in objects):
            continue
        if not _is_checkable(node):
            continue
        signature = inspect.signature(objects[node.func.id])
        try:
            signature.bind(*node.args, **{keyword.arg: keyword.value for keyword in node.keywords if keyword.arg})
        except TypeError as error:
            pytest.fail(f"{example.label}, line {node.lineno}: {node.func.id}(...) {error}")


def test_reference_documents_every_public_module():
    public = {
        ".".join(path.relative_to(SRC).with_suffix("").parts)
        for path in (SRC / PACKAGE).rglob("*.py")
        if not any(part.startswith("_") for part in path.relative_to(SRC).parts)
    }
    documented = {
        match["module"]
        for page in (DOCS / "reference").glob("*.md")
        for match in _REFERENCE_ENTRY.finditer(page.read_text(encoding="utf-8"))
    }
    assert sorted(public - documented) == []
    stale = [module for module in documented if importlib.util.find_spec(module) is None]
    assert stale == []
