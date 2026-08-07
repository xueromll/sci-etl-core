from __future__ import annotations

import pytest

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm.base import LLMClient
from sci_etl_core.llm.extraction import LLMEntityExtractor
from sci_etl_core.llm.relevance import LLMRelevanceFilter
from sci_etl_core.models import RawRecord


class TestOpenAICompatibleClient:
    @pytest.fixture
    def patched_openai(self, mocker):
        client_cls = mocker.patch("sci_etl_core.llm.openai_compatible.OpenAI")
        instance = client_cls.return_value
        return instance

    def _message(self, mocker, content):
        choice = mocker.Mock()
        choice.message.content = content
        response = mocker.Mock()
        response.choices = [choice]
        return response

    def test_parses_valid_json_response(self, patched_openai, mocker):
        from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient

        patched_openai.chat.completions.create.return_value = self._message(mocker, '{"relevant": true}')
        client = OpenAICompatibleClient(api_key="k", base_url="url", model="m")
        assert client.complete_json("sys", "user") == {"relevant": True}

    def test_empty_content_returns_empty_dict(self, patched_openai, mocker):
        from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient

        patched_openai.chat.completions.create.return_value = self._message(mocker, None)
        client = OpenAICompatibleClient(api_key="k", base_url="url", model="m")
        assert client.complete_json("sys", "user") == {}

    def test_corrupted_json_raises_llm_error(self, patched_openai, mocker):
        from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient

        patched_openai.chat.completions.create.return_value = self._message(mocker, "{ not json")
        client = OpenAICompatibleClient(api_key="k", base_url="url", model="m")
        with pytest.raises(LLMError):
            client.complete_json("sys", "user")

    def test_api_exception_is_wrapped_as_llm_error(self, patched_openai):
        from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient

        patched_openai.chat.completions.create.side_effect = RuntimeError("network down")
        client = OpenAICompatibleClient(api_key="k", base_url="url", model="m")
        with pytest.raises(LLMError, match="LLM completion failed"):
            client.complete_json("sys", "user")

    def test_timeout_override_is_passed_through(self, patched_openai, mocker):
        from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient

        patched_openai.chat.completions.create.return_value = self._message(mocker, "{}")
        client = OpenAICompatibleClient(api_key="k", base_url="url", model="m", default_timeout=99)
        client.complete_json("sys", "user", timeout=5)
        _, kwargs = patched_openai.chat.completions.create.call_args
        assert kwargs["timeout"] == 5


class TestLLMRelevanceFilter:
    def _client(self, mocker, result=None, exc=None):
        client = mocker.Mock(spec=LLMClient)
        if exc is not None:
            client.complete_json.side_effect = exc
        else:
            client.complete_json.return_value = result
        return client

    def test_relevant_true_when_llm_says_so(self, mocker):
        f = LLMRelevanceFilter(self._client(mocker, {"relevant": True}), "prompt")
        assert f.is_relevant(RawRecord("1", "t", "abstract")) is True

    def test_relevant_false_when_llm_says_so(self, mocker):
        f = LLMRelevanceFilter(self._client(mocker, {"relevant": False}), "prompt")
        assert f.is_relevant(RawRecord("1", "t", "abstract")) is False

    def test_missing_key_defaults_to_not_relevant(self, mocker):
        f = LLMRelevanceFilter(self._client(mocker, {}), "prompt")
        assert f.is_relevant(RawRecord("1", "t", "abstract")) is False

    @pytest.mark.parametrize("default", [True, False])
    def test_empty_abstract_uses_configured_default(self, mocker, default):
        f = LLMRelevanceFilter(self._client(mocker, {}), "prompt", default_on_empty_abstract=default)
        assert f.is_relevant(RawRecord("1", "t", "")) is default

    @pytest.mark.parametrize("default", [True, False])
    def test_llm_error_uses_configured_default(self, mocker, default):
        f = LLMRelevanceFilter(
            self._client(mocker, exc=LLMError("boom")), "prompt", default_on_error=default
        )
        assert f.is_relevant(RawRecord("1", "t", "abstract")) is default


class TestLLMEntityExtractor:
    def _client(self, mocker, result=None, exc=None):
        client = mocker.Mock(spec=LLMClient)
        if exc is not None:
            client.complete_json.side_effect = exc
        else:
            client.complete_json.return_value = result
        return client

    def test_returns_items_under_configured_key(self, mocker):
        client = self._client(mocker, {"galaxies": [{"name": "A"}, {"name": "B"}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="galaxies")
        assert extractor.extract("text") == [{"name": "A"}, {"name": "B"}]

    def test_single_unknown_key_is_unwrapped(self, mocker):
        client = self._client(mocker, {"whatever": [{"name": "A"}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        assert extractor.extract("text") == [{"name": "A"}]

    def test_returns_empty_on_unrecognized_shape(self, mocker):
        client = self._client(mocker, {"a": [], "b": []})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        assert extractor.extract("text") == []

    def test_llm_error_returns_empty_list(self, mocker):
        extractor = LLMEntityExtractor(self._client(mocker, exc=LLMError("x")), "prompt")
        assert extractor.extract("text") == []

    def test_html_input_is_converted_to_text(self, mocker):
        client = self._client(mocker, {"items": [{"ok": 1}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        extractor.extract("<html><body>Body text here</body></html>")
        sent = client.complete_json.call_args[0][1]
        assert "<html>" not in sent
        assert "Body text here" in sent

    def test_input_is_truncated_to_max_chars(self, mocker):
        client = self._client(mocker, {"items": []})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items", max_chars=100)
        extractor.extract("x" * 5000)
        sent = client.complete_json.call_args[0][1]
        assert len(sent) == 100

    def test_bytes_input_is_decoded(self, mocker):
        client = self._client(mocker, {"items": [{"ok": 1}]})
        extractor = LLMEntityExtractor(client, "prompt", result_key="items")
        assert extractor.extract(b"plain bytes body") == [{"ok": 1}]
