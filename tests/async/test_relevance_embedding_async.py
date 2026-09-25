from __future__ import annotations

import asyncio

import pytest

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.llm.relevance_embedding_async import AsyncEmbeddingRelevanceFilter
from sci_etl_core.models import RawRecord


class _TableEmbedder(AsyncEmbedder):
    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = table
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [self._table[text] for text in texts]


class _FailingEmbedder(AsyncEmbedder):
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def embed(self, texts):
        raise self._error


_TABLE = {"concept": [1.0, 0.0], "T\nA": [1.0, 0.0], "T\nB": [0.0, 1.0]}


class TestAsyncEmbeddingRelevanceFilter:
    def test_requires_at_least_one_reference(self):
        with pytest.raises(ValueError, match="at least one concept"):
            AsyncEmbeddingRelevanceFilter(_TableEmbedder(_TABLE), [])

    @pytest.mark.asyncio
    async def test_empty_abstract_returns_configured_default(self):
        keep = AsyncEmbeddingRelevanceFilter(_TableEmbedder(_TABLE), ["concept"])
        drop = AsyncEmbeddingRelevanceFilter(
            _TableEmbedder(_TABLE), ["concept"], default_on_empty_abstract=False
        )
        assert await keep.is_relevant(RawRecord(record_id="c", title="T", abstract="")) is True
        assert await drop.is_relevant(RawRecord(record_id="c", title="T", abstract="")) is False

    @pytest.mark.asyncio
    async def test_keeps_semantically_close_record(self):
        filt = AsyncEmbeddingRelevanceFilter(_TableEmbedder(_TABLE), ["concept"])
        assert await filt.is_relevant(RawRecord(record_id="a", title="T", abstract="A")) is True

    @pytest.mark.asyncio
    async def test_drops_distant_record(self):
        filt = AsyncEmbeddingRelevanceFilter(_TableEmbedder(_TABLE), ["concept"])
        assert await filt.is_relevant(RawRecord(record_id="b", title="T", abstract="B")) is False

    @pytest.mark.asyncio
    async def test_references_are_embedded_only_once(self):
        embedder = _TableEmbedder(_TABLE)
        filt = AsyncEmbeddingRelevanceFilter(embedder, ["concept"])
        await filt.is_relevant(RawRecord(record_id="a", title="T", abstract="A"))
        await filt.is_relevant(RawRecord(record_id="a", title="T", abstract="A"))
        assert embedder.calls.count(["concept"]) == 1

    @pytest.mark.asyncio
    async def test_embedding_error_returns_configured_default(self):
        filt = AsyncEmbeddingRelevanceFilter(
            _FailingEmbedder(EmbeddingError("down")), ["concept"], default_on_error=False
        )
        assert await filt.is_relevant(RawRecord(record_id="a", title="T", abstract="A")) is False

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self):
        filt = AsyncEmbeddingRelevanceFilter(
            _FailingEmbedder(asyncio.CancelledError()), ["concept"]
        )
        with pytest.raises(asyncio.CancelledError):
            await filt.is_relevant(RawRecord(record_id="a", title="T", abstract="A"))
