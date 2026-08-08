from __future__ import annotations

import json
from pathlib import Path

import aiofiles

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.async_base import AsyncStateManager


class AsyncFileStateManager(AsyncStateManager):
    def __init__(self, processed_ids_file: str | Path, metadata_file: str | Path) -> None:
        self._processed_ids_file = Path(processed_ids_file)
        self._metadata_file = Path(metadata_file)

    async def load_processed_ids(self) -> set[str]:
        if not self._processed_ids_file.is_file():
            return set()
        try:
            async with aiofiles.open(self._processed_ids_file, "r", encoding="utf-8") as handle:
                content = await handle.read()
        except OSError:
            return set()
        return {self._clean(line.strip()) for line in content.splitlines() if line.strip()}

    async def mark_processed(self, record_id: str) -> None:
        if not record_id:
            return
        async with aiofiles.open(self._processed_ids_file, "a", encoding="utf-8") as handle:
            await handle.write(f"{record_id}\n")

    async def load_metadata(self) -> PipelineMetadata:
        if not self._metadata_file.exists():
            return PipelineMetadata()
        try:
            async with aiofiles.open(self._metadata_file, "r", encoding="utf-8") as handle:
                raw = json.loads(await handle.read())
        except (OSError, json.JSONDecodeError):
            return PipelineMetadata()
        return PipelineMetadata(
            last_run_at=raw.get("last_run_date"), last_start_index=raw.get("last_start_index", 0)
        )

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        payload = {"last_run_date": metadata.last_run_at, "last_start_index": metadata.last_start_index}
        async with aiofiles.open(self._metadata_file, "w", encoding="utf-8") as handle:
            await handle.write(json.dumps(payload, indent=4))

    @staticmethod
    def _clean(raw_line: str) -> str:
        if "/abs/" in raw_line:
            return raw_line.split("/abs/")[-1]
        if "/pdf/" in raw_line:
            return raw_line.split("/pdf/")[-1].replace(".pdf", "")
        return raw_line
