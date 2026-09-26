from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from sci_etl_core.claims.models import Claim

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimChange:
    """One committed change to a record's claims: ``"replace"`` or ``"delete"``, at ``revision``."""

    revision: int
    record_id: str
    op: Literal["replace", "delete"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimChangePage:
    """Changes after a revision, oldest first; ``next_revision`` is where the next page starts."""

    changes: tuple[ClaimChange, ...]
    next_revision: int


class AsyncClaimStore(ABC):
    """An accumulating store of claims, replaced one record at a time.

    Every write records a change with a new revision in the same transaction,
    so a downstream consumer reads what changed by revision, which only grows
    and never depends on clocks.
    """

    @abstractmethod
    async def replace_record(self, record_id: str, claims: Sequence[Claim]) -> int:
        """Replace every claim of ``record_id`` in one transaction and return the new revision.

        An empty ``claims`` deletes the record's claims and still records a
        change. Claims with an id already seen in ``claims`` are dropped, and
        the number dropped is logged.

        Raises:
            ValueError: A claim's ``span.record_id`` is not ``record_id``.
            ClaimStoreError: The store cannot be written.
        """

    @abstractmethod
    async def delete_record(self, record_id: str) -> int:
        """Delete every claim of ``record_id`` and return the new revision."""

    @abstractmethod
    async def claims_for_records(self, record_ids: Collection[str]) -> dict[str, list[Claim]]:
        """Return the stored claims of each record in ``record_ids`` that has any, in stored order."""

    @abstractmethod
    async def changes_since(self, revision: int, limit: int = 1000) -> ClaimChangePage:
        """Return up to ``limit`` changes with a revision above ``revision``, oldest first.

        Raises:
            ValueError: ``limit`` is less than 1.
        """

    @abstractmethod
    async def revision(self) -> int:
        """Return the newest revision, or 0 before the first write."""

    @abstractmethod
    async def count(self) -> int:
        """Return how many claims are stored."""

    async def aclose(self) -> None:
        """Release the store's resources; the default does nothing."""
        return None


def unique_claims(record_id: str, claims: Sequence[Claim]) -> list[Claim]:
    """Check that every claim belongs to ``record_id`` and keep the first claim of each id.

    Raises:
        ValueError: A claim's ``span.record_id`` is not ``record_id``.
    """
    kept: dict[str, Claim] = {}
    for claim in claims:
        if claim.span.record_id != record_id:
            raise ValueError(f"Claim {claim.claim_id} belongs to {claim.span.record_id!r}, not {record_id!r}")
        kept.setdefault(claim.claim_id, claim)
    dropped = len(claims) - len(kept)
    if dropped:
        _logger.info("Dropped %d repeated claims of record %s", dropped, record_id)
    return list(kept.values())


def check_limit(limit: int) -> None:
    """Reject a page size below 1.

    Raises:
        ValueError: ``limit`` is less than 1.
    """
    if limit < 1:
        raise ValueError("limit must be a positive integer")
