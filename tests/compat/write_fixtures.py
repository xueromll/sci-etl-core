"""Write the persisted files of one sci-etl-core release into ``tests/compat/v<release>/``.

Run it once per release, against the tagged release installed in a throwaway
virtual environment, never against the working tree, and commit the output:

    python tests/compat/write_fixtures.py tests/compat/v0_4_0

The files are never regenerated. Every later release must keep opening them.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from sci_etl_core import (
    AsyncFileStateManager,
    AsyncSqliteEmbeddingStore,
    AsyncSqliteLLMResponseCache,
    AsyncSqliteStateManager,
    EmbeddingChunk,
    PipelineMetadata,
)
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.store_sqlite_fts5 import AsyncSqliteFts5Store

PROCESSED = ("2401.00001v1", "2401.00002v1")
METADATA = {"last_start_index": 40, "head_ids": ["2401.00009v1"], "head_offset": 0, "tail_ids": ["2401.00005v1"]}


async def write(directory: Path) -> None:
    metadata = PipelineMetadata(**METADATA)

    sqlite_state = AsyncSqliteStateManager(directory / "state.sqlite")
    for record_id in PROCESSED:
        await sqlite_state.mark_processed(record_id)
    await sqlite_state.save_metadata(metadata)
    await sqlite_state.flush()
    await sqlite_state.aclose()

    file_state = AsyncFileStateManager(directory / "processed_ids.txt", directory / "metadata.json")
    for record_id in PROCESSED:
        await file_state.mark_processed(record_id)
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


if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    asyncio.run(write(target))
