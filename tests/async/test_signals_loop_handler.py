from __future__ import annotations

import asyncio
import signal

import pytest

from sci_etl_core.signals import ShutdownSignal

TEST_SIGNAL = signal.SIGTERM


class TestLoopSignalHandler:
    @pytest.mark.asyncio
    async def test_loop_handler_is_installed_and_removed(self, mocker):
        loop = asyncio.get_running_loop()
        add = mocker.patch.object(loop, "add_signal_handler")
        remove = mocker.patch.object(loop, "remove_signal_handler")
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))

        with shutdown.guard():
            assert TEST_SIGNAL in shutdown._loop_handled

        add.assert_called_once()
        remove.assert_called_once()
