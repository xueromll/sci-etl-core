from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from sci_etl_core.embeddings.openai_compatible_async import AsyncOpenAIEmbedder
from sci_etl_core.exceptions import EmbeddingError


def _response(*vectors: list[float]) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in vectors])


def _timeout() -> APITimeoutError:
    return APITimeoutError(request=httpx.Request("POST", "https://x/v1/embeddings"))


def _build(mocker, *, max_retries: int = 3, create=None):
    embedder = AsyncOpenAIEmbedder(
        api_key="secret",
        base_url="https://x/v1",
        model="embed-model",
        batch_size=1,
        max_retries=max_retries,
        sleep=mocker.AsyncMock(),
    )
    client = mocker.Mock()
    client.embeddings.create = create or mocker.AsyncMock()
    client.close = mocker.AsyncMock()
    embedder._client = client
    return embedder, client


class TestAsyncOpenAIEmbedder:
    @pytest.mark.parametrize("max_retries", [0, -1])
    def test_max_retries_below_one_is_rejected(self, mocker, max_retries):
        with pytest.raises(ValueError, match="max_retries"):
            _build(mocker, max_retries=max_retries)

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, mocker):
        embedder, client = _build(mocker)
        assert await embedder.embed([]) == []
        client.embeddings.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_embeds_each_batch_in_order(self, mocker):
        create = mocker.AsyncMock(side_effect=[_response([1.0, 0.0]), _response([0.0, 1.0])])
        embedder, _ = _build(mocker, create=create)
        assert await embedder.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
        assert create.await_count == 2

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self, mocker):
        create = mocker.AsyncMock(side_effect=[_timeout(), _response([1.0])])
        embedder, _ = _build(mocker, create=create)
        assert await embedder.embed(["a"]) == [[1.0]]
        assert create.await_count == 2
        embedder._sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exhausted_retries_raise_embedding_error(self, mocker):
        create = mocker.AsyncMock(side_effect=_timeout())
        embedder, _ = _build(mocker, max_retries=2, create=create)
        with pytest.raises(EmbeddingError, match="after 2 attempts"):
            await embedder.embed(["a"])
        assert create.await_count == 2

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self, mocker):
        create = mocker.AsyncMock(side_effect=asyncio.CancelledError())
        embedder, _ = _build(mocker, create=create)
        with pytest.raises(asyncio.CancelledError):
            await embedder.embed(["a"])

    @pytest.mark.asyncio
    async def test_embedding_error_is_not_wrapped_again(self, mocker):
        create = mocker.AsyncMock(side_effect=EmbeddingError("already typed"))
        embedder, _ = _build(mocker, create=create)
        with pytest.raises(EmbeddingError, match="already typed"):
            await embedder.embed(["a"])

    @pytest.mark.asyncio
    async def test_unexpected_error_is_wrapped(self, mocker):
        create = mocker.AsyncMock(side_effect=ValueError("boom"))
        embedder, _ = _build(mocker, create=create)
        with pytest.raises(EmbeddingError, match="Embedding request failed: boom"):
            await embedder.embed(["a"])

    @pytest.mark.asyncio
    async def test_aclose_closes_client(self, mocker):
        embedder, client = _build(mocker)
        await embedder.aclose()
        client.close.assert_awaited_once()
