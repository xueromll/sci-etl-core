from __future__ import annotations

import pytest

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm.base import LLMClient
from sci_etl_core.llm.extraction import LLMEntityExtractor
from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient
from sci_etl_core.llm.relevance import LLMRelevanceFilter
from sci_etl_core.models import RawRecord


def _message(mocker, content):
    choice = mocker.Mock()
    choice.message.content = content
    response = mocker.Mock()
    response.choices = [choice]
    return response


class TestOpenAICompatibleClient:
    @pytest.fixture
    def patched_openai(self, mocker):
        instance = mocker.patch("sci_etl_core.llm.openai_compatible.AsyncOpenAI").return_value
        instance.chat.completions.create = mocker.AsyncMock()
        return instance

    def _client(self, mocker, **kwargs) -> OpenAICompatibleClient:
        kwargs.setdefault("sleep", mocker.AsyncMock())
        return OpenAICompatibleClient(api_key="k", base_url="url", model="m", **kwargs)

    @pytest.mark.asyncio
    async def test_parses_valid_json_response(self, patched_openai, mocker):
        patched_openai.chat.completions.create.return_value = _message(mocker, '{"relevant": true}')
        assert await self._client(mocker).complete_json("sys", "user") == {"relevant": True}

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty_dict(self, patched_openai, mocker):
        patched_openai.chat.completions.create.return_value = _message(mocker, None)
        assert await self._client(mocker).complete_json("sys", "user") == {}

    @pytest.mark.asyncio
    async def test_corrupted_json_raises_llm_error(self, patched_openai, mocker):
        patched_openai.chat.completions.create.return_value = _message(mocker, "{ not json")
        with pytest.raises(LLMError):
            await self._client(mocker).complete_json("sys", "user")

    @pytest.mark.asyncio
    async def test_api_exception_is_wrapped_as_llm_error(self, patched_openai, mocker):
        patched_openai.chat.completions.create.side_effect = RuntimeError("network down")
        with pytest.raises(LLMError, match="LLM completion failed"):
            await self._client(mocker).complete_json("sys", "user")

    @pytest.mark.asyncio
    async def test_empty_choices_raises(self, patched_openai, mocker):
        response = mocker.Mock()
        response.choices = []
        patched_openai.chat.completions.create.return_value = response
        with pytest.raises(LLMError, match="no choices"):
            await self._client(mocker).complete_json("sys", "user")

    @pytest.mark.asyncio
    async def test_timeout_override_is_passed_through(self, patched_openai, mocker):
        patched_openai.chat.completions.create.return_value = _message(mocker, "{}")
        await self._client(mocker, default_timeout=99).complete_json("sys", "user", timeout=5)
        assert patched_openai.chat.completions.create.call_args.kwargs["timeout"] == 5


class TestLLMRelevanceFilter:
    def _client(self, mocker, result=None, exc=None):
        client = mocker.Mock(spec=LLMClient)
        client.complete_json = mocker.AsyncMock(return_value=result, side_effect=exc)
        return client

    @pytest.mark.asyncio
    async def test_relevant_true_when_llm_says_so(self, mocker):
        f = LLMRelevanceFilter(self._client(mocker, {"relevant": True}), "prompt")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is True

    @pytest.mark.asyncio
    async def test_relevant_false_when_llm_says_so(self, mocker):
        f = LLMRelevanceFilter(self._client(mocker, {"relevant": False}), "prompt")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is False

    @pytest.mark.asyncio
    async def test_missing_key_defaults_to_not_relevant(self, mocker):
        f = LLMRelevanceFilter(self._client(mocker, {}), "prompt")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is False

    @pytest.mark.parametrize("default", [True, False])
    @pytest.mark.asyncio
    async def test_empty_abstract_uses_configured_default(self, mocker, default):
        f = LLMRelevanceFilter(self._client(mocker, {}), "prompt", default_on_empty_abstract=default)
        assert await f.is_relevant(RawRecord("1", "t", "")) is default

    @pytest.mark.parametrize("default", [True, False])
    @pytest.mark.asyncio
    async def test_llm_error_uses_configured_default(self, mocker, default):
        f = LLMRelevanceFilter(
            self._client(mocker, exc=LLMError("boom")), "prompt", default_on_error=default
        )
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is default


class TestLLMEntityExtractor:
    def _client(self, mocker, result=None, exc=None):
        client = mocker.Mock(spec=LLMClient)
        client.complete_json = mocker.AsyncMock(return_value=result, side_effect=exc)
        return client

    @pytest.mark.asyncio
    async def test_returns_items_under_configured_key(self, mocker):
        client = self._client(mocker, {"galaxies": [{"name": "A"}, {"name": "B"}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="galaxies")
        assert await extractor.extract("text") == [{"name": "A"}, {"name": "B"}]

    @pytest.mark.asyncio
    async def test_single_unknown_key_is_unwrapped(self, mocker):
        client = self._client(mocker, {"whatever": [{"name": "A"}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        assert await extractor.extract("text") == [{"name": "A"}]

    @pytest.mark.asyncio
    async def test_returns_empty_on_unrecognized_shape(self, mocker):
        client = self._client(mocker, {"a": [], "b": []})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        assert await extractor.extract("text") == []

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty_list(self, mocker):
        extractor = LLMEntityExtractor(self._client(mocker, exc=LLMError("x")), "prompt")
        assert await extractor.extract("text") == []

    @pytest.mark.asyncio
    async def test_html_input_is_converted_to_text(self, mocker):
        client = self._client(mocker, {"items": [{"ok": 1}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        await extractor.extract("<html><body>Body text here</body></html>")
        sent = client.complete_json.call_args[0][1]
        assert "<html>" not in sent
        assert "Body text here" in sent

    @pytest.mark.asyncio
    async def test_input_is_truncated_to_max_chars(self, mocker):
        client = self._client(mocker, {"items": []})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items", max_chars=100)
        await extractor.extract("x" * 5000)
        sent = client.complete_json.call_args[0][1]
        assert len(sent) == 100

    @pytest.mark.asyncio
    async def test_bytes_input_is_decoded(self, mocker):
        client = self._client(mocker, {"items": [{"ok": 1}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        assert await extractor.extract(b"plain bytes body") == [{"ok": 1}]


class TestLLMEntityExtractorTokenTruncation:
    def _client(self, mocker, result=None):
        client = mocker.Mock(spec=LLMClient)
        client.complete_json = mocker.AsyncMock(return_value=result)
        return client

    @pytest.mark.asyncio
    async def test_token_truncation_used_when_available(self, mocker):
        mocker.patch(
            "sci_etl_core.llm.extraction.truncate_to_tokens",
            return_value="token-truncated",
        )
        client = self._client(mocker, {"items": []})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items", max_tokens=32)
        await extractor.extract("some long body text")
        assert client.complete_json.call_args[0][1] == "token-truncated"
