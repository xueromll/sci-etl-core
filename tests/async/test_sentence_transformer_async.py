from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from sci_etl_core.embeddings.sentence_transformer_async import (
    AsyncSentenceTransformerEmbedder,
)
from sci_etl_core.exceptions import EmbeddingError


class _FakeModel:
    def __init__(self, name: str = "fake") -> None:
        self.name = name

    def encode(self, texts, convert_to_numpy=True):
        return np.array([[float(len(text)), 0.0] for text in texts])


def _install_fake_package(mocker) -> None:
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = _FakeModel
    mocker.patch.dict(sys.modules, {"sentence_transformers": module})


class TestAsyncSentenceTransformerEmbedder:
    @pytest.mark.asyncio
    async def test_embeds_with_injected_model(self):
        embedder = AsyncSentenceTransformerEmbedder(model=_FakeModel())
        assert await embedder.embed(["ab", "c"]) == [[2.0, 0.0], [1.0, 0.0]]

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        embedder = AsyncSentenceTransformerEmbedder(model=_FakeModel())
        assert await embedder.embed([]) == []

    def test_loads_named_model_when_none_injected(self, mocker):
        _install_fake_package(mocker)
        embedder = AsyncSentenceTransformerEmbedder("my-model")
        assert embedder._model.name == "my-model"

    def test_missing_dependency_raises_embedding_error(self, mocker):
        mocker.patch.dict(sys.modules, {"sentence_transformers": None})
        with pytest.raises(EmbeddingError, match="sentence-transformers is required"):
            AsyncSentenceTransformerEmbedder("my-model")
