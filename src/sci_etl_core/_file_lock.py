from __future__ import annotations

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import IO, Any

_LOCK_BYTES = 1


def _optional_module(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


fcntl = _optional_module("fcntl")
msvcrt = _optional_module("msvcrt")


@contextmanager
def exclusive_lock(handle: IO[Any]) -> Iterator[None]:
    """Hold an exclusive OS-level advisory lock on an open file for the block.

    Uses ``fcntl.flock`` on POSIX and ``msvcrt.locking`` on Windows; on a
    platform offering neither, the block runs unlocked so in-process
    serialization remains the only guarantee.
    """
    _acquire(handle)
    try:
        yield
    finally:
        _release(handle)


def _acquire(handle: IO[Any]) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    elif msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, _LOCK_BYTES)


def _release(handle: IO[Any]) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    elif msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTES)
