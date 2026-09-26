from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

from sci_etl_core.exceptions import ExportError
from sci_etl_core.exporters._entities import entity_to_dict
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.models import RawRecord


class AsyncJsonlExporter(AsyncExporter[Any]):
    """Append one JSON line per written record to a file.

    Each line is an object with the record's ``record_id``, ``title``, and
    ``source_url``, and its ``entities`` as a list, possibly empty. Nothing is
    merged: two papers that report one object give two lines, so conflicting
    values survive for review.

    Writes are buffered and appended on :meth:`flush`, which also calls
    ``fsync``, so ``durable_writes`` is ``False``. A record written again, in
    this run or a later one, appends another line; the last line for a
    ``record_id`` wins, which :func:`read_jsonl_export` applies. A repeated
    write therefore changes the file's bytes but not what a reader sees. A
    record whose last line has no entities holds none, so a re-extraction that
    finds nothing clears the record.

    Entities may be dicts, Pydantic models, dataclass instances, or claims.
    The file and its parent folder are created when the run opens the exporter.
    """

    durable_writes = False

    def __init__(self, path: str | Path, *, fsync: bool = True) -> None:
        """Configure the exporter; ``fsync=False`` skips the ``fsync`` after each flush, for tests and scratch runs."""
        self._path = Path(path)
        self._fsync = fsync
        self._pending: list[str] = []
        self._handle: IO[str] | None = None
        self._lock: asyncio.Lock | None = None

    @property
    def path(self) -> Path:
        """The file lines are appended to."""
        return self._path

    async def open(self) -> None:
        """Open the file for appending.

        Raises:
            ExportError: The file cannot be opened.
        """
        async with self._get_lock():
            if self._handle is None:
                self._handle = await asyncio.to_thread(self._open_file)

    async def write(self, record: RawRecord, entities: Sequence[Any]) -> None:
        """Queue the record's line for the next :meth:`flush`.

        Raises:
            TypeError: An entity is of a type that cannot be exported.
        """
        line = {
            "record_id": record.record_id,
            "title": record.title,
            "source_url": record.source_url,
            "entities": [entity_to_dict(entity) for entity in entities],
        }
        self._pending.append(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    async def flush(self) -> None:
        """Append the queued lines and ``fsync``; after a fault the lines stay queued and the file is truncated back.

        Raises:
            ExportError: The lines could not be written.
        """
        async with self._get_lock():
            if not self._pending:
                return
            if self._handle is None:
                self._handle = await asyncio.to_thread(self._open_file)
            payload = "".join(self._pending)
            await asyncio.to_thread(self._append, self._handle, payload)
            self._pending.clear()

    async def aclose(self) -> None:
        """Flush any queued lines and close the file; a later :meth:`open` reopens it."""
        await self.flush()
        async with self._get_lock():
            handle, self._handle = self._handle, None
        if handle is not None:
            await asyncio.to_thread(handle.close)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _open_file(self) -> IO[str]:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            return self._path.open("a", encoding="utf-8", newline="\n")
        except OSError as error:
            raise ExportError(f"Cannot open {self._path} for appending: {error}") from error

    def _append(self, handle: IO[str], payload: str) -> None:
        size = handle.tell()
        try:
            handle.write(payload)
            handle.flush()
            if self._fsync:
                os.fsync(handle.fileno())
        except OSError as error:
            try:
                handle.truncate(size)
                handle.seek(size)
            except OSError:
                pass
            raise ExportError(f"Cannot append to {self._path}: {error}") from error


def read_jsonl_export(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Read a file :class:`AsyncJsonlExporter` wrote, keeping the last line for each ``record_id``.

    Records come back in the order of their first line. A blank line is
    skipped.

    Raises:
        ExportError: A line is not a JSON object with ``record_id`` and
            ``entities``.
    """
    entities: dict[str, list[dict[str, Any]]] = {}
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                record_id, found = parsed["record_id"], parsed["entities"]
            except (ValueError, KeyError, TypeError) as error:
                raise ExportError(f"{path}:{number} is not an exported record line") from error
            entities[record_id] = found
    return entities
