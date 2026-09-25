from __future__ import annotations

import asyncio
import sqlite3

import pytest

from sci_etl_core._sqlite_async import AsyncSqliteRunner


class _RunnerFailure(Exception):
    pass


class _Opener:
    def __init__(self, path) -> None:
        self._path = path
        self.connections: list[sqlite3.Connection] = []

    def __call__(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, check_same_thread=False)
        self.connections.append(connection)
        return connection


def _select(value: int):
    return lambda connection: connection.execute(f"SELECT {value}").fetchone()[0]


def _raise(error: BaseException):
    def operation(connection):
        raise error

    return operation


@pytest.fixture
def opener(tmp_path) -> _Opener:
    return _Opener(tmp_path / "runner.db")


class TestAsyncSqliteRunnerConnection:
    def test_can_be_constructed_outside_a_running_loop(self, opener):
        runner = AsyncSqliteRunner(opener, error_factory=None)

        async def select_and_close() -> int:
            try:
                return await runner.run(_select(1), "select")
            finally:
                await runner.aclose()

        assert asyncio.run(select_and_close()) == 1

    @pytest.mark.asyncio
    async def test_opens_lazily_and_reuses_the_connection(self, opener):
        runner = AsyncSqliteRunner(opener, error_factory=None)
        assert opener.connections == []
        try:
            assert await runner.run(_select(1), "select") == 1
            assert await runner.run(_select(2), "select") == 2
            assert len(opener.connections) == 1
        finally:
            await runner.aclose()

    @pytest.mark.asyncio
    async def test_aclose_before_any_run_opens_nothing(self, opener):
        runner = AsyncSqliteRunner(opener, error_factory=None)
        await runner.aclose()
        assert opener.connections == []

    @pytest.mark.asyncio
    async def test_aclose_is_not_terminal(self, opener):
        runner = AsyncSqliteRunner(opener, error_factory=None)
        try:
            await runner.run(_select(1), "select")
            await runner.aclose()
            with pytest.raises(sqlite3.ProgrammingError):
                opener.connections[0].execute("SELECT 1")
            assert await runner.run(_select(1), "select") == 1
            assert len(opener.connections) == 2
        finally:
            await runner.aclose()

    @pytest.mark.asyncio
    async def test_failed_open_is_retried_by_the_next_run(self, opener):
        failures = [sqlite3.OperationalError("unable to open database file")]

        def open_connection() -> sqlite3.Connection:
            if failures:
                raise failures.pop()
            return opener()

        runner = AsyncSqliteRunner(open_connection, error_factory=None)
        try:
            with pytest.raises(sqlite3.OperationalError):
                await runner.run(_select(1), "select")
            assert await runner.run(_select(1), "select") == 1
            assert len(opener.connections) == 1
        finally:
            await runner.aclose()


class TestAsyncSqliteRunnerErrors:
    @pytest.mark.asyncio
    async def test_sqlite_error_propagates_unchanged_without_a_factory(self, opener):
        error = sqlite3.OperationalError("disk I/O error")
        runner = AsyncSqliteRunner(opener, error_factory=None)
        try:
            with pytest.raises(sqlite3.OperationalError) as caught:
                await runner.run(_raise(error), "write rows")
            assert caught.value is error
            assert caught.value.__cause__ is None
        finally:
            await runner.aclose()

    @pytest.mark.asyncio
    async def test_error_factory_replaces_sqlite_errors_naming_the_action(self, opener):
        error = sqlite3.OperationalError("disk I/O error")
        runner = AsyncSqliteRunner(opener, error_factory=_RunnerFailure)
        try:
            with pytest.raises(_RunnerFailure) as caught:
                await runner.run(_raise(error), "write rows")
            assert str(caught.value) == "Failed to write rows: disk I/O error"
            assert caught.value.__cause__ is error
        finally:
            await runner.aclose()

    @pytest.mark.asyncio
    async def test_error_factory_leaves_other_errors_unchanged(self, opener):
        error = ValueError("bad row")
        runner = AsyncSqliteRunner(opener, error_factory=_RunnerFailure)
        try:
            with pytest.raises(ValueError, match="bad row") as caught:
                await runner.run(_raise(error), "write rows")
            assert caught.value is error
        finally:
            await runner.aclose()


class TestAsyncSqliteRunnerCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_run_keeps_the_connection_until_its_thread_finishes(self, opener, statement_gate):
        gate = statement_gate(blocked_prefix="SELECT 1", observed_prefix="SELECT 2")
        runner = AsyncSqliteRunner(opener, error_factory=None)
        try:
            first = asyncio.create_task(runner.run(_select(1), "select"))
            await asyncio.to_thread(gate.blocked.wait, 5)
            first.cancel()
            second = asyncio.create_task(runner.run(_select(2), "select"))
            second_overlapped = await asyncio.to_thread(gate.observed.wait, 0.5)
            gate.release.set()
            await asyncio.to_thread(gate.finished.wait, 5)
            with pytest.raises(asyncio.CancelledError):
                await first
            assert not second_overlapped
            assert await second == 2
            assert gate.events == ["first-start", "first-end", "second-start"]
        finally:
            await runner.aclose()

    @pytest.mark.asyncio
    async def test_cancellation_wins_over_an_error_raised_after_it(self, opener, statement_gate):
        gate = statement_gate(blocked_prefix="SELECT missing", observed_prefix="SELECT 2")
        runner = AsyncSqliteRunner(opener, error_factory=_RunnerFailure)
        try:
            failing = asyncio.create_task(
                runner.run(lambda connection: connection.execute("SELECT missing FROM nowhere"), "select")
            )
            await asyncio.to_thread(gate.blocked.wait, 5)
            failing.cancel()
            gate.release.set()
            with pytest.raises(asyncio.CancelledError):
                await failing
            assert gate.events == ["first-start", "first-end"]
            assert await runner.run(_select(2), "select") == 2
        finally:
            await runner.aclose()
