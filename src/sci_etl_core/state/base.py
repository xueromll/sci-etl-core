from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core._deprecation import is_bundled, warn_deprecated
from sci_etl_core.models import PipelineMetadata


class StateManager(ABC):
    """Blocking counterpart of :class:`~sci_etl_core.state.async_base.AsyncStateManager`.

    Wrap an implementation in
    :class:`~sci_etl_core._adapters.SyncStateManagerAdapter` to use it in a
    pipeline. The blocking contract has no ``flush``.

    .. deprecated:: 0.5.0
        Subclassing it outside sci-etl-core emits a
        :class:`DeprecationWarning`. The blocking contracts will be removed in
        0.6.0; implement :class:`AsyncStateManager` instead.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_bundled(cls):
            warn_deprecated("The blocking StateManager contract", "implement AsyncStateManager instead", stacklevel=3)

    @abstractmethod
    def load_processed_ids(self) -> set[str]:
        """Return the set of record ids already processed."""

    @abstractmethod
    def mark_processed(self, record_id: str) -> None:
        """Persist a record id as processed."""

    @abstractmethod
    def load_metadata(self) -> PipelineMetadata:
        """Return the last saved pipeline metadata."""

    @abstractmethod
    def save_metadata(self, metadata: PipelineMetadata) -> None:
        """Persist pipeline metadata, stamping the current run time."""
