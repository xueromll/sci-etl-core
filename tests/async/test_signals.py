from __future__ import annotations

import asyncio
import signal
import threading
from unittest.mock import patch

import pytest

from sci_etl_core.signals import DEFAULT_SIGNALS, ShutdownSignal

TEST_SIGNAL = signal.SIGTERM


@pytest.fixture(autouse=True)
def restore_process_handlers():
    set_handler = signal.signal
    saved = {member: signal.getsignal(member) for member in DEFAULT_SIGNALS}
    yield
    for member, handler in saved.items():
        if handler is not None:
            set_handler(member, handler)


class TestShutdownSignalDefaults:
    def test_covers_interrupt_and_terminate(self):
        assert signal.SIGINT in DEFAULT_SIGNALS
        assert signal.SIGTERM in DEFAULT_SIGNALS

    def test_not_triggered_before_anything_happens(self):
        assert ShutdownSignal(signals=()).triggered is False

    def test_request_sets_the_flag(self):
        shutdown = ShutdownSignal(signals=())
        shutdown.request()
        assert shutdown.triggered is True

    @pytest.mark.asyncio
    async def test_wait_returns_once_requested(self):
        shutdown = ShutdownSignal(signals=())
        waiter = asyncio.create_task(shutdown.wait())
        await asyncio.sleep(0)
        assert not waiter.done()
        shutdown.request()
        await asyncio.wait_for(waiter, timeout=1)


class TestShutdownSignalInstallation:
    @pytest.mark.asyncio
    async def test_guard_yields_itself_and_restores_the_handler(self):
        original = signal.getsignal(TEST_SIGNAL)
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        with shutdown.guard() as entered:
            assert entered is shutdown
            assert signal.getsignal(TEST_SIGNAL) is not original
        assert signal.getsignal(TEST_SIGNAL) is original

    @pytest.mark.asyncio
    async def test_guard_restores_the_handler_when_the_body_raises(self):
        original = signal.getsignal(TEST_SIGNAL)
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        with pytest.raises(ValueError):
            with shutdown.guard():
                raise ValueError("body failed")
        assert signal.getsignal(TEST_SIGNAL) is original

    @pytest.mark.asyncio
    async def test_uninstall_clears_the_loop_reference(self):
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        with shutdown.guard():
            assert shutdown._loop is asyncio.get_running_loop()
        assert shutdown._loop is None

    @pytest.mark.asyncio
    async def test_falls_back_to_os_handler_when_loop_api_is_unavailable(self, mocker):
        loop = asyncio.get_running_loop()
        mocker.patch.object(loop, "add_signal_handler", side_effect=NotImplementedError)
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        with shutdown.guard():
            assert signal.getsignal(TEST_SIGNAL) == shutdown._on_os_signal
            assert shutdown._loop_handled == set()

    @pytest.mark.asyncio
    async def test_logs_when_no_handler_can_be_installed(self, mocker):
        logged: list[str] = []
        loop = asyncio.get_running_loop()
        mocker.patch.object(loop, "add_signal_handler", side_effect=NotImplementedError)
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,), logger=logged.append)
        with patch.object(signal, "signal", side_effect=ValueError("denied")):
            with shutdown.guard():
                assert shutdown._previous == {}
        assert any("unavailable" in message for message in logged)

    def test_install_is_skipped_off_the_main_thread(self):
        logged: list[str] = []
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,), logger=logged.append)

        async def install() -> None:
            shutdown.install()

        thread = threading.Thread(target=lambda: asyncio.run(install()))
        thread.start()
        thread.join()

        assert any("main thread" in message for message in logged)
        assert shutdown._loop_handled == set()
        assert shutdown._previous == {}

    def test_install_one_without_a_loop_is_a_noop(self):
        shutdown = ShutdownSignal(signals=())
        shutdown._install_one(TEST_SIGNAL)
        assert shutdown._loop_handled == set()
        assert shutdown._previous == {}

    def test_remove_loop_handler_skips_a_closed_loop(self):
        loop = asyncio.new_event_loop()
        loop.close()
        shutdown = ShutdownSignal(signals=())
        shutdown._loop = loop
        shutdown._loop_handled.add(TEST_SIGNAL)
        shutdown.uninstall()
        assert shutdown._loop_handled == set()
        assert shutdown._loop is None


class TestShutdownSignalHandlerCapture:
    def test_capture_keeps_the_first_recorded_handler(self):
        shutdown = ShutdownSignal(signals=())
        shutdown._previous[TEST_SIGNAL] = "sentinel"
        shutdown._capture_previous(TEST_SIGNAL)
        assert shutdown._previous[TEST_SIGNAL] == "sentinel"

    def test_capture_tolerates_a_failed_lookup(self, mocker):
        mocker.patch("sci_etl_core.signals.signal.getsignal", side_effect=ValueError("denied"))
        shutdown = ShutdownSignal(signals=())
        shutdown._capture_previous(TEST_SIGNAL)
        assert TEST_SIGNAL not in shutdown._previous

    def test_restore_skips_a_handler_that_python_cannot_address(self, mocker):
        setter = mocker.patch("sci_etl_core.signals.signal.signal")
        shutdown = ShutdownSignal(signals=())
        shutdown._restore_os_handler(TEST_SIGNAL, None)
        setter.assert_not_called()

    def test_restore_tolerates_a_rejected_handler(self, mocker):
        mocker.patch("sci_etl_core.signals.signal.signal", side_effect=ValueError("denied"))
        shutdown = ShutdownSignal(signals=())
        shutdown._restore_os_handler(TEST_SIGNAL, signal.SIG_DFL)
        assert shutdown._previous == {}


class TestShutdownSignalDelivery:
    @pytest.mark.asyncio
    async def test_loop_delivery_sets_the_flag_and_logs(self):
        logged: list[str] = []
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,), logger=logged.append)
        with shutdown.guard():
            shutdown._on_loop_signal(TEST_SIGNAL)
            assert shutdown.triggered is True
        assert any("flushing state" in message for message in logged)

    @pytest.mark.asyncio
    async def test_os_delivery_sets_the_flag_through_the_loop(self):
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        with shutdown.guard():
            shutdown._on_os_signal(int(TEST_SIGNAL), None)
            assert shutdown.triggered is False
            await asyncio.sleep(0)
            assert shutdown.triggered is True

    def test_os_delivery_without_a_loop_sets_the_flag_directly(self):
        shutdown = ShutdownSignal(signals=())
        shutdown._on_os_signal(int(TEST_SIGNAL), None)
        assert shutdown.triggered is True

    def test_os_delivery_with_a_closed_loop_sets_the_flag_directly(self):
        loop = asyncio.new_event_loop()
        loop.close()
        shutdown = ShutdownSignal(signals=())
        shutdown._loop = loop
        shutdown._on_os_signal(int(TEST_SIGNAL), None)
        assert shutdown.triggered is True


class TestShutdownSignalEscalation:
    @pytest.mark.asyncio
    async def test_second_loop_delivery_restores_and_reraises(self, mocker):
        raise_signal = mocker.patch("sci_etl_core.signals.signal.raise_signal")
        original = signal.getsignal(TEST_SIGNAL)
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        with shutdown.guard():
            shutdown._on_loop_signal(TEST_SIGNAL)
            shutdown._on_loop_signal(TEST_SIGNAL)
            assert signal.getsignal(TEST_SIGNAL) is original
        raise_signal.assert_called_once_with(TEST_SIGNAL)

    def test_second_os_delivery_reraises(self, mocker):
        raise_signal = mocker.patch("sci_etl_core.signals.signal.raise_signal")
        shutdown = ShutdownSignal(signals=())
        shutdown.request()
        shutdown._on_os_signal(int(TEST_SIGNAL), None)
        raise_signal.assert_called_once_with(TEST_SIGNAL)

    def test_escalation_is_logged(self, mocker):
        logged: list[str] = []
        mocker.patch("sci_etl_core.signals.signal.raise_signal")
        shutdown = ShutdownSignal(signals=(), logger=logged.append)
        shutdown.request()
        shutdown._on_loop_signal(TEST_SIGNAL)
        assert any("again" in message for message in logged)
