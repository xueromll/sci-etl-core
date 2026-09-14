from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class RawRecord:
    record_id: str
    title: str
    abstract: str
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PipelineMetadata:
    last_run_at: str | None = None
    last_start_index: int = 0

    def touch(self) -> None:
        """Stamp the current time as an ISO 8601 string with a UTC offset."""
        self.last_run_at = datetime.now(timezone.utc).isoformat()
