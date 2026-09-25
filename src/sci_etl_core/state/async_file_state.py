from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sci_etl_core._atomic_io import atomic_write_text
from sci_etl_core._file_lock import exclusive_lock
from sci_etl_core._migrations import newer_schema_message
from sci_etl_core.exceptions import StateStoreError
from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state._failures import bounded_error_text
from sci_etl_core.state.async_base import AsyncStateManager

SCHEMA_VERSION = 2
_FAILURES = "failures"


def _offset(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _ids(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(record_id, str) for record_id in value):
        return []
    return value


def _version(raw: dict[str, Any]) -> int:
    version = raw.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        return 1
    return version


def _cursor(raw: dict[str, Any]) -> str | None:
    if _version(raw) == 1:
        offset = _offset(raw.get("last_start_index", 0))
        return str(offset) if offset else None
    cursor = raw.get("cursor")
    return cursor if isinstance(cursor, str) else None


def _failures(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    failures = raw.get(_FAILURES)
    if not isinstance(failures, dict):
        return {}
    return {
        record_id: entry
        for record_id, entry in failures.items()
        if isinstance(entry, dict) and _offset(entry.get("attempts")) > 0
    }


class AsyncFileStateManager(AsyncStateManager):
    """Plain-file state backend hardened against concurrent access.

    In-process callers are serialized by an :class:`asyncio.Lock`; other
    processes are excluded by an OS-level advisory lock held for the whole of
    every read or append. Metadata is published by atomic rename, so an
    interrupted write cannot truncate it. Blocking file work runs in a worker
    thread to keep the loop responsive.

    The metadata file is JSON with a ``schema_version``; a file without one was
    written by sci-etl-core 0.4, and its saved offset is read as the cursor.
    Failed attempts are kept in the metadata file per record, with the last
    error truncated to 4,096 characters, and :meth:`mark_processed` clears
    them.

    A file that cannot be read raises ``OSError`` rather than reading as empty,
    because an empty processed-id set would silently reprocess every record.
    """

    def __init__(self, processed_ids_file: str | Path, metadata_file: str | Path) -> None:
        self._processed_ids_file = Path(processed_ids_file)
        self._metadata_file = Path(metadata_file)
        self._lock: asyncio.Lock | None = None
        self._failed_ids: set[str] | None = None

    async def load_processed_ids(self) -> set[str]:
        """Return the processed ids.

        Raises:
            OSError: The ids file exists but cannot be read.
        """
        async with self._get_lock():
            return await asyncio.to_thread(self._read_ids)

    async def mark_processed(self, record_id: str) -> None:
        """Record an id as processed and clear its failed attempts.

        An empty or whitespace-only id carries nothing to track and is ignored.

        Raises:
            ValueError: ``record_id`` has leading or trailing whitespace, which
                the file cannot store faithfully: lines are stripped when read,
                so the id would come back changed, never match the record again,
                and the record would be reprocessed on every run. Also raised
                when ``record_id`` contains a line boundary, meaning any
                character :meth:`str.splitlines` splits on (``\\n``, ``\\r``,
                ``\\x0b``, ``\\x0c``, ``\\x1c``-``\\x1e``, ``\\x85``,
                ``\\u2028``, ``\\u2029``). The file stores one id per line, so
                writing it would be read back as several distinct ids, silently
                marking records that were never seen.
            StateStoreError: The record had failed attempts and the metadata
                file was written by a newer sci-etl-core.
        """
        if not record_id or not record_id.strip():
            return
        if record_id.strip() != record_id:
            raise ValueError(
                "record_id must not have leading or trailing whitespace; "
                f"{record_id!r} would be read back as {record_id.strip()!r}"
            )
        if record_id.splitlines() != [record_id]:
            raise ValueError(
                "record_id must not contain a line boundary; "
                f"{record_id!r} would corrupt the processed-ids file"
            )
        async with self._get_lock():
            await asyncio.to_thread(self._append_id, record_id)
            if self._failed_ids is None:
                await asyncio.to_thread(self._read_metadata)
            if self._failed_ids is not None and record_id in self._failed_ids:
                await asyncio.to_thread(self._update_metadata, lambda raw: raw[_FAILURES].pop(record_id, None))

    async def record_failure(self, record_id: str, error: str) -> int:
        """Count a failed attempt and keep ``error``, truncated to 4,096 characters; an empty id is ignored.

        Raises:
            OSError: The metadata file cannot be read or written.
            StateStoreError: The metadata file was written by a newer sci-etl-core.
        """
        if not record_id:
            return 0
        attempts = 0

        def count(raw: dict[str, Any]) -> None:
            nonlocal attempts
            failures = raw[_FAILURES]
            attempts = _offset(failures.get(record_id, {}).get("attempts")) + 1
            failures[record_id] = {"attempts": attempts, "last_error": bounded_error_text(error)}

        async with self._get_lock():
            await asyncio.to_thread(self._update_metadata, count)
        return attempts

    async def failure_counts(self) -> dict[str, int]:
        """Return the attempts per record id that has failed and not been marked processed since.

        Raises:
            OSError: The metadata file exists but cannot be read.
            StateStoreError: The metadata file was written by a newer sci-etl-core.
        """
        async with self._get_lock():
            raw = await asyncio.to_thread(self._read_metadata)
        return {record_id: entry["attempts"] for record_id, entry in _failures(raw).items()}

    async def load_metadata(self) -> PipelineMetadata:
        """Return the saved metadata.

        Content that is not valid metadata, such as a hand-edited file, yields
        the defaults: resuming from the first page rescans the listing, and ids
        already processed are still skipped, so nothing is lost.

        Raises:
            OSError: The metadata file exists but cannot be read.
            StateStoreError: The metadata file was written by a newer sci-etl-core.
        """
        async with self._get_lock():
            raw = await asyncio.to_thread(self._read_metadata)
        last_run_at = raw.get("last_run_date")
        if not isinstance(last_run_at, str):
            last_run_at = None
        return PipelineMetadata(
            last_run_at=last_run_at,
            cursor=_cursor(raw),
            truncated=raw.get("truncated") is True,
            head_ids=_ids(raw.get("head_ids", [])),
            head_offset=_offset(raw.get("head_offset", 0)),
            tail_ids=_ids(raw.get("tail_ids", [])),
        )

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        """Persist metadata, keeping the failed attempts already recorded.

        Raises:
            OSError: The metadata file cannot be read or written.
            StateStoreError: The metadata file was written by a newer sci-etl-core.
        """
        metadata.touch()
        payload = {
            "last_run_date": metadata.last_run_at,
            "cursor": metadata.cursor,
            "truncated": metadata.truncated,
            "head_ids": list(metadata.head_ids),
            "head_offset": metadata.head_offset,
            "tail_ids": list(metadata.tail_ids),
        }
        async with self._get_lock():
            await asyncio.to_thread(self._update_metadata, lambda raw: raw.update(payload))

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _read_ids(self) -> set[str]:
        if not self._processed_ids_file.is_file():
            return set()
        with self._processed_ids_file.open("r", encoding="utf-8") as handle:
            with exclusive_lock(handle):
                content = handle.read()
        return {line.strip() for line in content.splitlines() if line.strip()}

    def _append_id(self, record_id: str) -> None:
        self._processed_ids_file.parent.mkdir(parents=True, exist_ok=True)
        with self._processed_ids_file.open("a", encoding="utf-8") as handle:
            with exclusive_lock(handle):
                handle.write(f"{record_id}\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _read_metadata(self) -> dict[str, Any]:
        raw = self._read_metadata_file()
        if _version(raw) > SCHEMA_VERSION:
            raise StateStoreError(newer_schema_message("state metadata file", _version(raw), SCHEMA_VERSION))
        self._failed_ids = set(_failures(raw))
        return raw

    def _read_metadata_file(self) -> dict[str, Any]:
        if not self._metadata_file.exists():
            return {}
        try:
            with self._metadata_file.open("r", encoding="utf-8") as handle:
                with exclusive_lock(handle):
                    raw = json.loads(handle.read())
        except ValueError:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _update_metadata(self, change: Callable[[dict[str, Any]], object]) -> None:
        raw = self._read_metadata()
        if _version(raw) == 1:
            raw["cursor"] = _cursor(raw)
        raw.pop("last_start_index", None)
        raw[_FAILURES] = _failures(raw)
        change(raw)
        raw["schema_version"] = SCHEMA_VERSION
        atomic_write_text(self._metadata_file, json.dumps(raw, indent=4))
        self._failed_ids = set(raw[_FAILURES])
