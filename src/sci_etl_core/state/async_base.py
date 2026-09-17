from __future__ import annotations

from abc import ABC, abstractmethod

from sci_etl_core.models import PipelineMetadata


class AsyncStateManager(ABC):
    """Contract for the durable record of which records a run has settled.

    A pipeline loads the processed ids and metadata once per run, marks each
    settled record as processed, possibly concurrently, saves metadata after
    every page, and calls :meth:`flush` when the run ends, however it ends.
    """

    @abstractmethod
    async def load_processed_ids(self) -> set[str]:
        """Return the set of record ids already processed."""

    @abstractmethod
    async def mark_processed(self, record_id: str) -> None:
        """Persist a record id as processed."""

    @abstractmethod
    async def load_metadata(self) -> PipelineMetadata:
        """Return the last saved pipeline metadata."""

    @abstractmethod
    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        """Persist pipeline metadata, stamping the current run time."""

    async def flush(self) -> None:
        """Force buffered state to durable storage before termination.

        Backends that commit on every mutation need no action, so the default
        is a no-op.
        """
        return None
