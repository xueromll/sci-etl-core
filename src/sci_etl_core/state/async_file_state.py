from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from sci_etl_core._atomic_io import atomic_write_text
from sci_etl_core._file_lock import exclusive_lock
from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager


class AsyncFileStateManager(AsyncStateManager):
    """Plain-file state backend hardened against concurrent access.

    In-process callers are serialized by an :class:`asyncio.Lock`; other
    processes are excluded by an OS-level advisory lock held for the whole of
    every read or append. Metadata is published by atomic rename, so an
    interrupted write cannot truncate it. Blocking file work runs in a worker
    thread to keep the loop responsive.
    """

    def __init__(self, processed_ids_file: str | Path, metadata_file: str | Path) -> None:
        self._processed_ids_file = Path(processed_ids_file)
        self._metadata_file = Path(metadata_file)
        self._lock: asyncio.Lock | None = None

    async def load_processed_ids(self) -> set[str]:
        async with self._get_lock():
            return await asyncio.to_thread(self._read_ids)

    async def mark_processed(self, record_id: str) -> None:
        """Record an id as processed.

        Raises:
            ValueError: ``record_id`` contains a line break. The file stores one
                id per line, so writing it would be read back as several
                distinct ids, silently marking records that were never seen.
        """
        if not record_id:
            return
        record_id = record_id.strip()
        if not record_id:
            return
        if "\n" in record_id or "\r" in record_id:
            raise ValueError(
                "record_id must not contain a line break; "
                f"{record_id!r} would corrupt the processed-ids file"
            )
        async with self._get_lock():
            await asyncio.to_thread(self._append_id, record_id)

    async def load_metadata(self) -> PipelineMetadata:
        async with self._get_lock():
            raw = await asyncio.to_thread(self._read_metadata)
        return PipelineMetadata(
            last_run_at=raw.get("last_run_date"), last_start_index=raw.get("last_start_index", 0)
        )

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        payload = {
            "last_run_date": metadata.last_run_at,
            "last_start_index": metadata.last_start_index,
        }
        async with self._get_lock():
            await asyncio.to_thread(self._write_metadata, payload)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _read_ids(self) -> set[str]:
        if not self._processed_ids_file.is_file():
            return set()
        try:
            with self._processed_ids_file.open("r", encoding="utf-8") as handle:
                with exclusive_lock(handle):
                    content = handle.read()
        except OSError:
            return set()
        return {line.strip() for line in content.splitlines() if line.strip()}

    def _append_id(self, record_id: str) -> None:
        self._processed_ids_file.parent.mkdir(parents=True, exist_ok=True)
        with self._processed_ids_file.open("a", encoding="utf-8") as handle:
            with exclusive_lock(handle):
                handle.write(f"{record_id}\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _read_metadata(self) -> dict[str, Any]:
        if not self._metadata_file.exists():
            return {}
        try:
            with self._metadata_file.open("r", encoding="utf-8") as handle:
                with exclusive_lock(handle):
                    raw = json.loads(handle.read())
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_metadata(self, payload: dict[str, Any]) -> None:
        atomic_write_text(self._metadata_file, json.dumps(payload, indent=4))
