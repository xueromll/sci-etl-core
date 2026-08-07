from __future__ import annotations

from importlib import import_module
from typing import Any, Callable


def lazy_exports(
    package: str, namespace: dict[str, Any], exports: dict[str, str]
) -> tuple[Callable[[str], Any], Callable[[], list[str]]]:
    """Build a package's ``__getattr__`` and ``__dir__`` that import on first use.

    ``exports`` maps each public name to the module defining it. Importing the
    package therefore never pulls in an optional dependency such as ``openai``
    or ``pdfplumber``; that cost is paid only when a name needing it is first
    accessed, and the resolved object is cached in ``namespace`` afterwards.
    """

    def __getattr__(name: str) -> Any:
        module_name = exports.get(name)
        if module_name is None:
            raise AttributeError(f"module {package!r} has no attribute {name!r}")
        value = getattr(import_module(module_name), name)
        namespace[name] = value
        return value

    def __dir__() -> list[str]:
        return sorted({*namespace, *exports})

    return __getattr__, __dir__
