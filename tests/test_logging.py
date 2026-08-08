from __future__ import annotations

import logging as std_logging

from sci_etl_core import logging as log_module


def _patch_file_handler(mocker):
    mocker.patch.object(log_module.logging, "FileHandler", return_value=mocker.MagicMock())


class TestConfigureLogging:
    def test_configures_file_and_console_handlers(self, mocker):
        log_module._CONFIGURED_LOGGERS.clear()
        _patch_file_handler(mocker)
        logger = log_module.configure_logging("test.logger.a", "ignored.log")
        assert logger.propagate is False
        assert len(logger.handlers) == 2
        log_module.logging.FileHandler.assert_called_once()

    def test_returns_cached_logger_on_second_call(self, mocker):
        log_module._CONFIGURED_LOGGERS.clear()
        _patch_file_handler(mocker)
        first = log_module.configure_logging("test.logger.b", "x.log")
        second = log_module.configure_logging("test.logger.b", "x.log")
        assert first is second
        log_module.logging.FileHandler.assert_called_once()

    def test_custom_level_is_applied(self, mocker):
        log_module._CONFIGURED_LOGGERS.clear()
        _patch_file_handler(mocker)
        logger = log_module.configure_logging("test.logger.c", "x.log", level=std_logging.DEBUG)
        assert logger.level == std_logging.DEBUG
