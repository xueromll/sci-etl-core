"""Collect the messages sci-etl-core logs during one test.

:func:`capture_logs` attaches a handler to the ``sci_etl_core`` logger that
appends each message to the returned list, and lowers the logger's level so
``INFO`` lines arrive too. The autouse fixture in ``tests/conftest.py`` calls
:func:`release_captures` after every test.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger("sci_etl_core")
_HANDLERS: list[logging.Handler] = []
_SAVED_LEVELS: list[int] = []


class _ListHandler(logging.Handler):
    def __init__(self, lines: list[str]) -> None:
        super().__init__(logging.DEBUG)
        self.lines = lines

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def capture_logs() -> list[str]:
    lines: list[str] = []
    handler = _ListHandler(lines)
    if not _HANDLERS:
        _SAVED_LEVELS.append(_LOGGER.level)
    _HANDLERS.append(handler)
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.DEBUG)
    return lines


def release_captures() -> None:
    while _HANDLERS:
        _LOGGER.removeHandler(_HANDLERS.pop())
    while _SAVED_LEVELS:
        _LOGGER.setLevel(_SAVED_LEVELS.pop())
