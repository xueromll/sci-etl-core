from __future__ import annotations

import logging as std_logging
import os

from sci_etl_core import log_utils as log_module


def _patch_file_handler(mocker):
    mocker.patch.object(log_module.logging, "FileHandler", return_value=mocker.MagicMock())


def _close_handlers(logger):
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


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

    def test_creates_the_log_folder_when_missing(self, tmp_path):
        log_module._CONFIGURED_LOGGERS.clear()
        log_file = tmp_path / "logs" / "nested" / "run.log"
        logger = log_module.configure_logging("test.logger.d", log_file)
        try:
            logger.info("hello")
            assert "hello" in log_file.read_text(encoding="utf-8")
        finally:
            _close_handlers(logger)
            log_module._CONFIGURED_LOGGERS.clear()

    def test_changed_file_or_level_replaces_the_handlers(self, mocker):
        log_module._CONFIGURED_LOGGERS.clear()
        mocker.patch.object(
            log_module.logging, "FileHandler", side_effect=lambda *args, **kwargs: mocker.MagicMock()
        )
        first = log_module.configure_logging("test.logger.e", "first.log")
        replaced = list(first.handlers)
        second = log_module.configure_logging("test.logger.e", "second.log", level=std_logging.DEBUG)
        assert second is first
        assert len(second.handlers) == 2
        assert not set(replaced) & set(second.handlers)
        replaced[0].close.assert_called_once()
        assert second.level == std_logging.DEBUG
        assert log_module.logging.FileHandler.call_args.args[0] == os.path.abspath("second.log")
