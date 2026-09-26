from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Literal

from sci_etl_core.claims.models import Claim
from sci_etl_core.claims.store_base import (
    AsyncClaimStore,
    ClaimChange,
    ClaimChangePage,
    check_limit,
    unique_claims,
)


class InMemoryClaimStore(AsyncClaimStore):
    """A claim store that lives as long as the process."""

    def __init__(self) -> None:
        self._claims: dict[str, list[Claim]] = {}
        self._changes: list[ClaimChange] = []

    async def replace_record(self, record_id: str, claims: Sequence[Claim]) -> int:
        kept = unique_claims(record_id, claims)
        if kept:
            self._claims[record_id] = kept
        else:
            self._claims.pop(record_id, None)
        return self._record_change(record_id, "replace")

    async def delete_record(self, record_id: str) -> int:
        self._claims.pop(record_id, None)
        return self._record_change(record_id, "delete")

    async def claims_for_records(self, record_ids: Collection[str]) -> dict[str, list[Claim]]:
        return {record_id: list(self._claims[record_id]) for record_id in record_ids if record_id in self._claims}

    async def changes_since(self, revision: int, limit: int = 1000) -> ClaimChangePage:
        check_limit(limit)
        changes = tuple(change for change in self._changes if change.revision > revision)[:limit]
        return ClaimChangePage(changes=changes, next_revision=changes[-1].revision if changes else revision)

    async def revision(self) -> int:
        return len(self._changes)

    async def count(self) -> int:
        return sum(len(claims) for claims in self._claims.values())

    def _record_change(self, record_id: str, op: Literal["replace", "delete"]) -> int:
        revision = len(self._changes) + 1
        self._changes.append(ClaimChange(revision=revision, record_id=record_id, op=op))
        return revision
