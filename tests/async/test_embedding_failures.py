from __future__ import annotations

import math

import pytest

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.embeddings.sentence_transformer_async import AsyncSentenceTransformerEmbedder
from sci_etl_core.exceptions import EmbeddingError
from sci_etl_core.llm.relevance_embedding_async import AsyncEmbeddingRelevanceFilter
from sci_etl_core.models import RawRecord

RECORD = RawRecord("a", "T", "A")


class _ScriptedEmbedder(AsyncEmbedder):
    def __init__(self, references, record_vectors) -> None:
        self._references = references
        self._record_vectors = record_vectors
        self.reference_calls = 0

    async def embed(self, texts):
        if list(texts) == ["concept"]:
            self.reference_calls += 1
            return self._references
        return self._record_vectors


class TestEmbeddingRelevanceUnusableVectors:
    @pytest.mark.parametrize("default", [True, False])
    @pytest.mark.parametrize(
        "record_vectors",
        [
            [],
            [[0.0, 0.0]],
            [[math.nan, 1.0]],
            [[1.0, math.inf]],
            [[1.0, 0.0, 0.0]],
            [[1.0, 0.0], [1.0, 0.0]],
            [[[1.0], [0.0]]],
        ],
        ids=["none", "zero", "nan", "inf", "wrong-dimension", "too-many", "not-a-vector"],
    )
    @pytest.mark.asyncio
    async def test_unusable_record_vector_returns_default_on_error(self, record_vectors, default):
        filt = AsyncEmbeddingRelevanceFilter(
            _ScriptedEmbedder([[1.0, 0.0]], record_vectors), ["concept"], default_on_error=default
        )
        assert await filt.is_relevant(RECORD) is default

    @pytest.mark.asyncio
    async def test_inconsistent_reference_vectors_return_default_and_are_retried(self):
        embedder = _ScriptedEmbedder([[1.0, 0.0], [1.0]], [[1.0, 0.0]])
        filt = AsyncEmbeddingRelevanceFilter(embedder, ["concept"], default_on_error=False)
        assert await filt.is_relevant(RECORD) is False
        assert await filt.is_relevant(RECORD) is False
        assert embedder.reference_calls == 2

    @pytest.mark.asyncio
    async def test_usable_vector_is_still_scored(self):
        filt = AsyncEmbeddingRelevanceFilter(
            _ScriptedEmbedder([[1.0, 0.0]], [[0.0, 1.0]]), ["concept"], default_on_error=True
        )
        assert await filt.is_relevant(RECORD) is False


class TestSentenceTransformerFailures:
    @pytest.mark.asyncio
    async def test_encode_failure_is_raised_as_embedding_error(self):
        class FailingModel:
            def encode(self, texts, convert_to_numpy=True):
                raise RuntimeError("CUDA out of memory")

        embedder = AsyncSentenceTransformerEmbedder(model=FailingModel())
        with pytest.raises(EmbeddingError, match="CUDA out of memory"):
            await embedder.embed(["text"])
