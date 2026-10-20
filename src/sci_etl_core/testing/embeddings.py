"""The contract suite for vector stores.

Subclass :class:`EmbeddingStoreContract` in a test module under a name pytest
collects, such as ``TestMyStore``, and give it a ``make_store`` fixture:

```python
import pytest

from sci_etl_core.testing import EmbeddingStoreContract

from my_package import MyEmbeddingStore


class TestMyStore(EmbeddingStoreContract):
    @pytest.fixture
    def make_store(self, tmp_path):
        return lambda: MyEmbeddingStore(tmp_path / "vectors.db")
```

The tests are plain functions that run each scenario with :func:`asyncio.run`,
so pytest-asyncio is not needed.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from sci_etl_core.embeddings.store_base import AsyncEmbeddingStore, EmbeddingChunk, StoredRecord
from sci_etl_core.exceptions import SciEtlError

_QUERY = [1.0, 0.0, 0.0]


def _chunk(
    record_id: str, chunk_index: int, text: str, vector: list[float], metadata: dict[str, Any] | None = None
) -> EmbeddingChunk:
    return EmbeddingChunk(record_id, chunk_index, text, vector, dict(metadata or {}))


def _chunks() -> list[EmbeddingChunk]:
    return [
        _chunk("alpha", 0, "alpha first passage", [1.0, 0.0, 0.0], {"title": "Alpha"}),
        _chunk("alpha", 1, "alpha second passage", [0.0, 1.0, 0.0], {"title": "Alpha"}),
        _chunk("beta", 0, "beta passage", [1.0, 1.0, 0.0]),
        _chunk("gamma", 0, "gamma passage", [0.0, 0.0, 1.0]),
    ]


@asynccontextmanager
async def _session(make_store: Callable[[], AsyncEmbeddingStore]) -> AsyncIterator[AsyncEmbeddingStore]:
    store = make_store()
    try:
        yield store
    finally:
        await store.aclose()


class EmbeddingStoreContract:
    """Tests every :class:`~sci_etl_core.embeddings.store_base.AsyncEmbeddingStore` must pass.

    A subclass provides the ``make_store`` fixture. It returns a callable that
    takes no argument and returns a new store over the same storage each time
    it is called, and the storage starts empty in every test. The suite calls
    it inside a running event loop and awaits ``aclose()`` on each store it
    creates. A store that keeps its chunks in memory returns the same instance
    on every call.

    A subclass may also override the ``write_newer_schema`` fixture to check
    that storage from a newer release is refused.

    Vectors have three dimensions, and scores are compared to within
    ``1e-5``, so a store may keep float32 vectors. Some tests check an
    optional capability and skip when the implementation lacks it:
    ``iter_records``, when the store keeps the default that raises
    ``NotImplementedError``, and the schema-version test, when
    ``write_newer_schema`` returns ``None``.
    """

    @pytest.fixture
    def write_newer_schema(self) -> Callable[[], None] | None:
        """Return a callable that writes storage from a newer schema version, or ``None``.

        The suite calls it before it creates a store. The default returns
        ``None``, which skips the schema-version test; override it when the
        store records a schema version.
        """
        return None

    def test_new_store_is_empty(self, make_store: Callable[[], AsyncEmbeddingStore]) -> None:
        """A new store counts no chunk and matches no query."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                assert await store.count() == 0
                assert await store.query(_QUERY) == []

        asyncio.run(scenario())

    def test_add_replaces_a_chunk_with_the_same_id_and_index(
        self, make_store: Callable[[], AsyncEmbeddingStore]
    ) -> None:
        """Adding a chunk again under its record id and index replaces it instead of adding another."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add([_chunk("alpha", 0, "old passage", [1.0, 0.0, 0.0])])
                await store.add([_chunk("alpha", 0, "new passage", [1.0, 0.0, 0.0])])
                assert await store.count() == 1
                assert [hit.text for hit in await store.query(_QUERY)] == ["new passage"]

        asyncio.run(scenario())

    def test_chunks_persist_across_instances(self, make_store: Callable[[], AsyncEmbeddingStore]) -> None:
        """Chunks added by one store are counted and found by the next."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add(_chunks())
            async with _session(make_store) as store:
                assert await store.count() == 4
                hits = await store.query(_QUERY, top_k=1)
                assert [(hit.record_id, hit.chunk_index) for hit in hits] == [("alpha", 0)]

        asyncio.run(scenario())

    def test_query_ranks_by_cosine_similarity(self, make_store: Callable[[], AsyncEmbeddingStore]) -> None:
        """Hits come best first with their cosine score, text, and metadata, at most ``top_k`` of them."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add(_chunks())
                best, second = await store.query(_QUERY, top_k=2)
                assert (best.record_id, best.chunk_index, best.text) == ("alpha", 0, "alpha first passage")
                assert best.metadata == {"title": "Alpha"}
                assert best.score == pytest.approx(1.0, abs=1e-5)
                assert (second.record_id, second.chunk_index) == ("beta", 0)
                assert second.score == pytest.approx(1 / math.sqrt(2), abs=1e-5)
                hits = await store.query(_QUERY, top_k=10)
                assert len(hits) == 4
                assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)

        asyncio.run(scenario())

    def test_query_honors_min_score_and_exclude_record_id(self, make_store: Callable[[], AsyncEmbeddingStore]) -> None:
        """``min_score`` drops weaker hits, and ``exclude_record_id`` drops one record's chunks."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add(_chunks())
                strong = await store.query(_QUERY, top_k=10, min_score=0.5)
                assert [hit.record_id for hit in strong] == ["alpha", "beta"]
                others = await store.query(_QUERY, top_k=10, min_score=0.5, exclude_record_id="alpha")
                assert [hit.record_id for hit in others] == ["beta"]

        asyncio.run(scenario())

    def test_a_non_finite_vector_never_matches(self, make_store: Callable[[], AsyncEmbeddingStore]) -> None:
        """A stored vector holding NaN is never returned as a hit."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add([*_chunks(), _chunk("broken", 0, "broken passage", [math.nan, 0.0, 0.0])])
                hits = await store.query(_QUERY, top_k=10)
                assert "broken" not in {hit.record_id for hit in hits}
                assert all(math.isfinite(hit.score) for hit in hits)

        asyncio.run(scenario())

    def test_delete_record_removes_every_chunk_of_the_record(
        self, make_store: Callable[[], AsyncEmbeddingStore]
    ) -> None:
        """``delete_record`` removes all of one record's chunks and ignores an unknown record."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add(_chunks())
                await store.delete_record("alpha")
                await store.delete_record("unknown")
                assert await store.count() == 2
                assert "alpha" not in {hit.record_id for hit in await store.query(_QUERY, top_k=10)}

        asyncio.run(scenario())

    def test_replace_record_leaves_only_the_new_chunks(self, make_store: Callable[[], AsyncEmbeddingStore]) -> None:
        """``replace_record`` drops a record's old chunks, even those with a higher index."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add(_chunks())
                await store.replace_record("alpha", [_chunk("alpha", 0, "alpha replaced", [1.0, 0.0, 0.0])])
                assert await store.count() == 3
                hits = await store.query(_QUERY, top_k=10)
                alpha = [(hit.chunk_index, hit.text) for hit in hits if hit.record_id == "alpha"]
                assert alpha == [(0, "alpha replaced")]

        asyncio.run(scenario())

    def test_iter_records_yields_passages_in_record_id_order(
        self, make_store: Callable[[], AsyncEmbeddingStore]
    ) -> None:
        """``iter_records`` yields each record's passages in chunk order, records in id order, at any batch size."""
        expected = [
            StoredRecord("alpha", ("alpha first passage", "alpha second passage"), {"title": "Alpha"}),
            StoredRecord("beta", ("beta passage",), {}),
            StoredRecord("gamma", ("gamma passage",), {}),
        ]

        async def scenario() -> None:
            async with _session(make_store) as store:
                if type(store).iter_records is AsyncEmbeddingStore.iter_records:
                    pytest.skip(f"{type(store).__name__} cannot enumerate its stored records")
                await store.add(list(reversed(_chunks())))
                assert [record async for record in store.iter_records()] == expected
                assert [record async for record in store.iter_records(batch_size=1)] == expected

        asyncio.run(scenario())

    def test_aclose_then_reuse(self, make_store: Callable[[], AsyncEmbeddingStore]) -> None:
        """A closed store keeps working, with the chunks it held before ``aclose()``."""

        async def scenario() -> None:
            async with _session(make_store) as store:
                await store.add(_chunks()[:1])
                await store.aclose()
                assert await store.count() == 1
                await store.add(_chunks()[1:])
                assert await store.count() == 4

        asyncio.run(scenario())

    def test_a_newer_schema_version_is_refused(
        self, make_store: Callable[[], AsyncEmbeddingStore], write_newer_schema: Callable[[], None] | None
    ) -> None:
        """Storage from a newer schema version raises a ``SciEtlError`` on read and on write."""
        if write_newer_schema is None:
            pytest.skip("write_newer_schema is not provided")
        write_newer_schema()

        async def scenario() -> None:
            async with _session(make_store) as store:
                with pytest.raises(SciEtlError):
                    await store.count()
                with pytest.raises(SciEtlError):
                    await store.add(_chunks())

        asyncio.run(scenario())
