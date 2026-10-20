"""Write the persisted files of one sci-etl-core release into ``tests/compat/v<release>/``.

Run it once per release, against the tagged release installed in a throwaway
virtual environment, never against the working tree, and commit the output:

    python tests/compat/write_fixtures.py tests/compat/v0_6_0

The files are never regenerated. Every later release must keep opening them.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from sci_etl_core import (
    AsyncFileStateManager,
    AsyncJsonlExporter,
    AsyncSqliteEmbeddingStore,
    AsyncSqliteLLMResponseCache,
    AsyncSqliteStateManager,
    EmbeddingChunk,
    PipelineMetadata,
    RawRecord,
)
from sci_etl_core.claims import (
    AsyncSqliteClaimStore,
    AsyncSqliteRejectionStore,
    Claim,
    ClaimContext,
    EvidenceSpan,
    ExtractionStamp,
    Quantity,
    RejectedEntity,
    make_claim_id,
    rejection_id,
)
from sci_etl_core.processors.validation import Violation
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store

PROCESSED = ("2401.00001v1", "2401.00002v1")
METADATA = {"cursor": "40", "head_ids": ["2401.00009v1"], "head_offset": 0, "tail_ids": ["2401.00005v1"]}
FAILED = "2401.00003v1"
STAMP = ExtractionStamp(model="model-a", prompt_hash="prompt", schema_hash="schema", extractor_version="0.6.0")
REJECTED = ({"subject": "DF44", "value": -1}, {"subject": "DF2", "value": -2})


def _claim() -> Claim:
    span = EvidenceSpan(record_id="2401.00001v1", start=0, end=40, quote="DF44 has a stellar mass of 3e8 M_sun.")
    quantity = Quantity(verbatim="3e8 M_sun", value=3e8, unit_text="M_sun")
    context = ClaimContext.from_mapping({"band": "V"})
    claim_id = make_claim_id(
        record_id=span.record_id,
        kind="measurement",
        subject="DF44",
        predicate="stellar mass",
        object="",
        polarity=0,
        context=context,
        quantity=quantity,
        span=span,
        schema_hash=STAMP.schema_hash,
    )
    return Claim(
        claim_id=claim_id,
        kind="measurement",
        subject="DF44",
        predicate="stellar mass",
        span=span,
        stamp=STAMP,
        quantity=quantity,
        context=context,
        confidence=0.9,
    )


def _rejection(entity: dict[str, int]) -> RejectedEntity:
    violations = (Violation(code="out-of-range", field="value", severity="error", message="value is negative"),)
    return RejectedEntity(
        entry_id=rejection_id("2401.00001v1", entity, violations, STAMP),
        record_id="2401.00001v1",
        entity=entity,
        violations=violations,
        stamp=STAMP,
        quote="a negative value",
        created_at="2026-09-27T00:00:00+00:00",
    )


async def write(directory: Path) -> None:
    metadata = PipelineMetadata(**METADATA)

    sqlite_state = AsyncSqliteStateManager(directory / "state.sqlite")
    for record_id in PROCESSED:
        await sqlite_state.mark_processed(record_id)
    await sqlite_state.record_failure(FAILED, "timeout")
    await sqlite_state.save_metadata(metadata)
    await sqlite_state.flush()
    await sqlite_state.aclose()

    file_state = AsyncFileStateManager(directory / "processed_ids.txt", directory / "metadata.json")
    for record_id in PROCESSED:
        await file_state.mark_processed(record_id)
    await file_state.record_failure(FAILED, "timeout")
    await file_state.save_metadata(PipelineMetadata(**METADATA))

    cache = AsyncSqliteLLMResponseCache(
        directory / "llm_cache.sqlite", now=lambda: datetime(2026, 9, 16, tzinfo=UTC)
    )
    await cache.set("key", {"relevant": True})
    await cache.aclose()

    embeddings = AsyncSqliteEmbeddingStore(directory / "embeddings.sqlite")
    await embeddings.add(
        [EmbeddingChunk(record_id="2401.00001v1", chunk_index=0, text="dwarf galaxies", vector=[0.6, 0.8])]
    )
    await embeddings.aclose()

    index = AsyncSqliteFts5Store(directory / "search.sqlite", facet_keys=("categories",))
    await index.index(
        [SearchDocument("2401.00001v1", "Dwarf galaxies", "An abstract", "A body", {"categories": ["astro-ph.GA"]})]
    )
    await index.aclose()

    claims = AsyncSqliteClaimStore(directory / "claims.sqlite")
    await claims.replace_record("2401.00001v1", [_claim()])
    await claims.aclose()

    rejections = AsyncSqliteRejectionStore(
        directory / "rejections.sqlite", now=lambda: datetime(2026, 9, 27, tzinfo=UTC)
    )
    entries = [_rejection(entity) for entity in REJECTED]
    await rejections.put(entries)
    await rejections.resolve(entries[1].entry_id, "corrected", {"subject": "DF2", "value": 2})
    await rejections.aclose()

    exporter = AsyncJsonlExporter(directory / "export.jsonl")
    await exporter.open()
    await exporter.write(
        RawRecord(record_id="2401.00001v1", title="Dwarf galaxies", abstract="An abstract"), [{"name": "DF44"}]
    )
    await exporter.write(RawRecord(record_id="2401.00002v1", title="No entities", abstract="An abstract"), [])
    await exporter.aclose()


if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    asyncio.run(write(target))
