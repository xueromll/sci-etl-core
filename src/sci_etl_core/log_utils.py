from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import NamedTuple


class _Configuration(NamedTuple):
    logger: logging.Logger
    log_file: str
    level: int
    handlers: tuple[logging.Handler, ...]


_CONFIGURED_LOGGERS: dict[str, _Configuration] = {}


def configure_logging(name: str, log_file: str | Path, level: int = logging.INFO) -> logging.Logger:
    """Return a logger that writes to ``log_file`` and to stdout.

    A repeated call with the same file and level returns the logger unchanged.
    A call with a different file or level replaces the handlers this function
    installed earlier, closing the old file, so the logger always reflects the
    latest request. The log file's folder is created when it does not exist.
    """
    target = os.path.abspath(log_file)
    current = _CONFIGURED_LOGGERS.get(name)
    if current is not None and (current.log_file, current.level) == (target, level):
        return current.logger

    logger = logging.getLogger(name)
    if current is not None:
        _detach(logger, current.handlers)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    Path(target).parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(target, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    _CONFIGURED_LOGGERS[name] = _Configuration(logger, target, level, (file_handler, console_handler))
    return logger


def _detach(logger: logging.Logger, handlers: tuple[logging.Handler, ...]) -> None:
    for handler in handlers:
        logger.removeHandler(handler)
        handler.close()
