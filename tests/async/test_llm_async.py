from __future__ import annotations

import pytest

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.extraction_async import AsyncLLMEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncLLMRelevanceFilter
from sci_etl_core.models import RawRecord


def _message(mocker, content):
    choice = mocker.Mock()
    choice.message.content = content
    response = mocker.Mock()
    response.choices = [choice]
    return response


def _async_llm(mocker, result=None, exc=None):
    client = mocker.Mock(spec=AsyncLLMClient)
    client.complete_json = mocker.AsyncMock(return_value=result, side_effect=exc)
    return client


class TestAsyncOpenAICompatibleClient:
    @pytest.fixture
    def patched(self, mocker):
        instance = mocker.patch("sci_etl_core.llm.openai_compatible_async.AsyncOpenAI").return_value
        instance.chat.completions.create = mocker.AsyncMock()
        return instance

    def _make(self, mocker, **kwargs):
        from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient

        kwargs.setdefault("default_timeout", 99)
        kwargs.setdefault("sleep", mocker.AsyncMock())
        return AsyncOpenAICompatibleClient(api_key="k", base_url="u", model="m", **kwargs)

    @pytest.mark.asyncio
    async def test_parses_valid_json_response(self, patched, mocker):
        patched.chat.completions.create.return_value = _message(mocker, '{"relevant": true}')
        assert await self._make(mocker).complete_json("s", "u") == {"relevant": True}

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty_dict(self, patched, mocker):
        patched.chat.completions.create.return_value = _message(mocker, None)
        assert await self._make(mocker).complete_json("s", "u") == {}

    @pytest.mark.asyncio
    async def test_corrupted_json_raises_llm_error(self, patched, mocker):
        patched.chat.completions.create.return_value = _message(mocker, "{ not json")
        with pytest.raises(LLMError):
            await self._make(mocker).complete_json("s", "u")

    @pytest.mark.asyncio
    async def test_api_exception_is_wrapped(self, patched, mocker):
        patched.chat.completions.create.side_effect = RuntimeError("network down")
        with pytest.raises(LLMError, match="LLM completion failed"):
            await self._make(mocker).complete_json("s", "u")

    @pytest.mark.asyncio
    async def test_timeout_override_is_passed_through(self, patched, mocker):
        patched.chat.completions.create.return_value = _message(mocker, "{}")
        await self._make(mocker).complete_json("s", "u", timeout=5)
        assert patched.chat.completions.create.call_args.kwargs["timeout"] == 5

    @pytest.mark.asyncio
    async def test_empty_choices_raises(self, patched, mocker):
        response = mocker.Mock()
        response.choices = []
        patched.chat.completions.create.return_value = response
        with pytest.raises(LLMError, match="no choices"):
            await self._make(mocker).complete_json("s", "u")

    @pytest.mark.asyncio
    async def test_retryable_error_then_success(self, patched, mocker):
        from openai import APITimeoutError

        class FakeTimeout(APITimeoutError):
            def __init__(self):
                Exception.__init__(self, "timeout")

        patched.chat.completions.create.side_effect = [FakeTimeout(), _message(mocker, '{"ok": 1}')]
        assert await self._make(mocker, max_retries=3).complete_json("s", "u") == {"ok": 1}

    @pytest.mark.asyncio
    async def test_retryable_error_exhausts_and_raises(self, patched, mocker):
        from openai import RateLimitError

        class FakeRateLimit(RateLimitError):
            def __init__(self):
                Exception.__init__(self, "rate limited")

        patched.chat.completions.create.side_effect = FakeRateLimit()
        sleep = mocker.AsyncMock()
        client = self._make(mocker, max_retries=3, sleep=sleep)
        with pytest.raises(LLMError, match="after 3 attempts"):
            await client.complete_json("s", "u")
        assert patched.chat.completions.create.await_count == 3
        assert sleep.await_count == 2


class TestAsyncLLMRelevanceFilter:
    @pytest.mark.asyncio
    async def test_relevant_true(self, mocker):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, {"relevant": True}), "p")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is True

    @pytest.mark.asyncio
    async def test_relevant_false(self, mocker):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, {"relevant": False}), "p")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is False

    @pytest.mark.asyncio
    async def test_missing_key_defaults_to_false(self, mocker):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, {}), "p")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is False

    @pytest.mark.parametrize("default", [True, False])
    @pytest.mark.asyncio
    async def test_empty_abstract_uses_default(self, mocker, default):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, {}), "p", default_on_empty_abstract=default)
        assert await f.is_relevant(RawRecord("1", "t", "")) is default

    @pytest.mark.parametrize("default", [True, False])
    @pytest.mark.asyncio
    async def test_error_uses_default(self, mocker, default):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, exc=LLMError("boom")), "p", default_on_error=default)
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is default


class TestAsyncLLMEntityExtractor:
    @pytest.mark.asyncio
    async def test_returns_items_under_key(self, mocker):
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, {"galaxies": [{"name": "A"}]}), "p", result_key="galaxies")
        assert await ex.extract("text") == [{"name": "A"}]

    @pytest.mark.asyncio
    async def test_single_unknown_key_is_unwrapped(self, mocker):
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, {"whatever": [{"name": "A"}]}), "p", result_key="items")
        assert await ex.extract("text") == [{"name": "A"}]

    @pytest.mark.asyncio
    async def test_unrecognized_shape_returns_empty(self, mocker):
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, {"a": [], "b": []}), "p", result_key="items")
        assert await ex.extract("text") == []

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, mocker):
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, exc=LLMError("x")), "p")
        assert await ex.extract("text") == []

    @pytest.mark.asyncio
    async def test_html_input_is_converted(self, mocker):
        client = _async_llm(mocker, {"items": [{"ok": 1}]})
        ex = AsyncLLMEntityExtractor(client, "p", result_key="items")
        await ex.extract("<html><body>Body text here</body></html>")
        sent = client.complete_json.call_args[0][1]
        assert "<html>" not in sent
        assert "Body text here" in sent

    @pytest.mark.asyncio
    async def test_input_is_truncated(self, mocker):
        client = _async_llm(mocker, {"items": []})
        ex = AsyncLLMEntityExtractor(client, "p", result_key="items", max_chars=100)
        await ex.extract("x" * 5000)
        assert len(client.complete_json.call_args[0][1]) == 100

    @pytest.mark.asyncio
    async def test_bytes_input_is_decoded(self, mocker):
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, {"items": [{"ok": 1}]}), "p", result_key="items")
        assert await ex.extract(b"plain bytes body") == [{"ok": 1}]
