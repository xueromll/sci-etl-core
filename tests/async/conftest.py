from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_REAL_CONNECT = sqlite3.connect


class StatementGate:
    def __init__(self, blocked_prefix: str, observed_prefix: str) -> None:
        self._blocked_prefix = blocked_prefix
        self._observed_prefix = observed_prefix
        self.events: list[str] = []
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.observed = threading.Event()
        gate = self

        class GatedConnection(sqlite3.Connection):
            def execute(self, sql, *parameters):
                return gate.step(sql, super().execute, *parameters)

            def executemany(self, sql, *parameters):
                return gate.step(sql, super().executemany, *parameters)

        self._factory = GatedConnection

    def connect(self, *args, **kwargs) -> sqlite3.Connection:
        return _REAL_CONNECT(*args, factory=self._factory, **kwargs)

    def step(self, sql, run, *parameters):
        if sql.startswith(self._observed_prefix):
            self.events.append("second-start")
            self.observed.set()
        if not sql.startswith(self._blocked_prefix) or self.blocked.is_set():
            return run(sql, *parameters)
        self.events.append("first-start")
        self.blocked.set()
        self.release.wait(5)
        try:
            return run(sql, *parameters)
        finally:
            self.events.append("first-end")
            self.finished.set()


@pytest.fixture
def statement_gate(mocker):
    def install(blocked_prefix: str, observed_prefix: str) -> StatementGate:
        gate = StatementGate(blocked_prefix, observed_prefix)
        mocker.patch.object(sqlite3, "connect", side_effect=gate.connect)
        return gate

    return install
