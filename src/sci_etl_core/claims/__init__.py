"""Claims and provenance: each extracted value with its paper, its evidence sentence, and what produced it.

Every name here is provisional: it may change in a minor release, with a
CHANGELOG entry, until a known consumer depends on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "AsyncClaimStore": "sci_etl_core.claims.store_base",
    "AsyncClaimStoreExporter": "sci_etl_core.claims.exporter_async",
    "AsyncLLMClaimExtractor": "sci_etl_core.claims.extractor_async",
    "AsyncRejectionStore": "sci_etl_core.claims.rejections",
    "AsyncSqliteClaimStore": "sci_etl_core.claims.store_sqlite_async",
    "AsyncSqliteRejectionStore": "sci_etl_core.claims.rejections",
    "CanonicalValue": "sci_etl_core.claims.models",
    "Claim": "sci_etl_core.claims.models",
    "ClaimChange": "sci_etl_core.claims.store_base",
    "ClaimChangePage": "sci_etl_core.claims.store_base",
    "ClaimContext": "sci_etl_core.claims.models",
    "ClaimDraft": "sci_etl_core.claims.drafts",
    "EvidenceSpan": "sci_etl_core.claims.models",
    "ExtractionStamp": "sci_etl_core.claims.models",
    "InMemoryClaimStore": "sci_etl_core.claims.store_memory",
    "InMemoryRejectionStore": "sci_etl_core.claims.rejections",
    "Quantity": "sci_etl_core.claims.models",
    "QuantityDraft": "sci_etl_core.claims.drafts",
    "RejectedEntity": "sci_etl_core.claims.rejections",
    "Statistics": "sci_etl_core.claims.models",
    "StatisticsDraft": "sci_etl_core.claims.drafts",
    "content_hash": "sci_etl_core.claims.models",
    "locate_quote": "sci_etl_core.claims.locate",
    "make_claim_id": "sci_etl_core.claims.models",
    "rejection_id": "sci_etl_core.claims.rejections",
    "sentence_bounds": "sci_etl_core.claims.locate",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.claims.drafts import ClaimDraft, QuantityDraft, StatisticsDraft
    from sci_etl_core.claims.exporter_async import AsyncClaimStoreExporter
    from sci_etl_core.claims.extractor_async import AsyncLLMClaimExtractor
    from sci_etl_core.claims.locate import locate_quote, sentence_bounds
    from sci_etl_core.claims.models import (
        CanonicalValue,
        Claim,
        ClaimContext,
        EvidenceSpan,
        ExtractionStamp,
        Quantity,
        Statistics,
        content_hash,
        make_claim_id,
    )
    from sci_etl_core.claims.rejections import (
        AsyncRejectionStore,
        AsyncSqliteRejectionStore,
        InMemoryRejectionStore,
        RejectedEntity,
        rejection_id,
    )
    from sci_etl_core.claims.store_base import AsyncClaimStore, ClaimChange, ClaimChangePage
    from sci_etl_core.claims.store_memory import InMemoryClaimStore
    from sci_etl_core.claims.store_sqlite_async import AsyncSqliteClaimStore
