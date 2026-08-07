from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED_LOGGERS: dict[str, logging.Logger] = {}


def configure_logging(name: str, log_file: str | Path, level: int = logging.INFO) -> logging.Logger:
    if name in _CONFIGURED_LOGGERS:
        return _CONFIGURED_LOGGERS[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    _CONFIGURED_LOGGERS[name] = logger
    return logger
