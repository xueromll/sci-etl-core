from __future__ import annotations

import json
from pathlib import Path

from sci_etl_core.models import PipelineMetadata
from sci_etl_core.state.base import StateManager


class FileStateManager(StateManager):
    def __init__(self, processed_ids_file: str | Path, metadata_file: str | Path) -> None:
        self._processed_ids_file = Path(processed_ids_file)
        self._metadata_file = Path(metadata_file)

    def load_processed_ids(self) -> set[str]:
        if not self._processed_ids_file.is_file():
            return set()
        try:
            with self._processed_ids_file.open("r", encoding="utf-8") as handle:
                return {self._clean(line.strip()) for line in handle if line.strip()}
        except OSError:
            return set()

    def mark_processed(self, record_id: str) -> None:
        if not record_id:
            return
        with self._processed_ids_file.open("a", encoding="utf-8") as handle:
            handle.write(f"{record_id}\n")

    def load_metadata(self) -> PipelineMetadata:
        if not self._metadata_file.exists():
            return PipelineMetadata()
        try:
            with self._metadata_file.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            return PipelineMetadata(
                last_run_at=raw.get("last_run_date"), last_start_index=raw.get("last_start_index", 0)
            )
        except (OSError, json.JSONDecodeError):
            return PipelineMetadata()

    def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        payload = {"last_run_date": metadata.last_run_at, "last_start_index": metadata.last_start_index}
        with self._metadata_file.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4)

    @staticmethod
    def _clean(raw_line: str) -> str:
        if "/abs/" in raw_line:
            return raw_line.split("/abs/")[-1]
        if "/pdf/" in raw_line:
            return raw_line.split("/pdf/")[-1].replace(".pdf", "")
        return raw_line
