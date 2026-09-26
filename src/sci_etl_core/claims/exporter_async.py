from __future__ import annotations

from collections.abc import Sequence

from sci_etl_core.claims.models import Claim
from sci_etl_core.claims.store_base import AsyncClaimStore
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.models import RawRecord


class AsyncClaimStoreExporter(AsyncExporter[Claim]):
    """Store each record's claims in an :class:`~sci_etl_core.claims.store_base.AsyncClaimStore`.

    ``write`` replaces the record's claims in one transaction and returns once
    they are committed, so ``durable_writes`` is ``True``. The last write for
    a record wins, and a write with no claims clears the record's claims.

    When ``write`` raises :class:`~sci_etl_core.exceptions.ClaimStoreError`,
    the pipeline fails the record: it is not marked processed, counts one
    failed attempt, and is retried on the next run. After ``max_attempts``
    counted attempts it is quarantined at listing time like any failing
    record. This is not a memory fault: the pipeline absorbs only
    :data:`~sci_etl_core.ingest_protocol.MEMORY_FAULTS`, and this exporter
    never raises one.
    """

    durable_writes = True

    def __init__(self, store: AsyncClaimStore) -> None:
        self._store = store

    @property
    def store(self) -> AsyncClaimStore:
        """The store claims are written to."""
        return self._store

    async def write(self, record: RawRecord, entities: Sequence[Claim]) -> None:
        """Replace ``record``'s claims with ``entities``.

        Raises:
            ClaimStoreError: The store could not be written.
            ValueError: A claim belongs to another record.
        """
        await self._store.replace_record(record.record_id, entities)

    async def aclose(self) -> None:
        """Close the store; it reopens on its next use."""
        await self._store.aclose()
