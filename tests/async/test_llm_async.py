from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.extraction_async import AsyncLLMEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncLLMRelevanceFilter
from sci_etl_core.models import RawRecord, TokenUsage
from sci_etl_core.processors.validation import NumericRangeValidator, RecordValidator


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

    @pytest.mark.asyncio
    async def test_aclose_closes_the_underlying_client(self, patched, mocker):
        patched.close = mocker.AsyncMock()
        await self._make(mocker).aclose()
        patched.close.assert_awaited_once()

    @pytest.mark.parametrize("max_retries", [0, -1])
    def test_max_retries_below_one_is_rejected(self, patched, mocker, max_retries):
        with pytest.raises(ValueError, match="max_retries"):
            self._make(mocker, max_retries=max_retries)

    def test_negative_retry_after_cap_is_rejected(self, patched, mocker):
        with pytest.raises(ValueError, match="max_retry_after"):
            self._make(mocker, max_retry_after=-1)

    def test_sdk_retries_are_disabled_so_one_retry_policy_applies(self, patched, mocker):
        from sci_etl_core.llm import openai_compatible_async

        self._make(mocker)
        assert openai_compatible_async.AsyncOpenAI.call_args.kwargs["max_retries"] == 0

    @pytest.mark.asyncio
    async def test_retry_waits_as_long_as_the_server_asks(self, patched, mocker):
        from openai import RateLimitError

        response = httpx.Response(
            429,
            headers={"retry-after": "12"},
            request=httpx.Request("POST", "https://api.example/v1/chat/completions"),
        )
        patched.chat.completions.create.side_effect = [
            RateLimitError("rate limited", response=response, body=None),
            _message(mocker, '{"ok": 1}'),
        ]
        sleep = mocker.AsyncMock()
        assert await self._make(mocker, sleep=sleep).complete_json("s", "u") == {"ok": 1}
        sleep.assert_awaited_once_with(12.0)

    @pytest.mark.asyncio
    async def test_usage_accumulates_across_responses(self, patched, mocker):
        first = _message(mocker, "{}")
        first.usage = SimpleNamespace(prompt_tokens=120, completion_tokens=8)
        rejected = _message(mocker, "not json")
        rejected.usage = SimpleNamespace(prompt_tokens=30, completion_tokens=None)
        patched.chat.completions.create.side_effect = [first, rejected]
        client = self._make(mocker)
        await client.complete_json("s", "u")
        with pytest.raises(LLMError):
            await client.complete_json("s", "u")
        assert client.usage == TokenUsage(requests=2, prompt_tokens=150, completion_tokens=8)
        client.usage.prompt_tokens = 0
        assert client.usage.prompt_tokens == 150


class TestAsyncLLMRelevanceFilter:
    @pytest.mark.asyncio
    async def test_relevant_true(self, mocker):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, {"relevant": True}), "p")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is True

    @pytest.mark.asyncio
    async def test_relevant_false(self, mocker):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, {"relevant": False}), "p")
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is False

    @pytest.mark.parametrize("default", [True, False])
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"relevant": None},
            {"relevant": "maybe"},
            {"relevant": 2},
            {"relevant": [True]},
            [{"relevant": False}],
            "false",
        ],
    )
    @pytest.mark.asyncio
    async def test_unclear_verdict_uses_default_on_error(self, mocker, payload, default):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, payload), "p", default_on_error=default)
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is default

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("false", False),
            (" FALSE ", False),
            ("no", False),
            ("0", False),
            (0, False),
            (0.0, False),
            ("true", True),
            ("Yes", True),
            ("1", True),
            (1, True),
            (1.0, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_textual_and_numeric_verdicts_are_read_strictly(self, mocker, value, expected):
        f = AsyncLLMRelevanceFilter(
            _async_llm(mocker, {"relevant": value}), "p", default_on_error=not expected
        )
        assert await f.is_relevant(RawRecord("1", "t", "abstract")) is expected

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
    async def test_error_propagates_instead_of_reading_as_no_entities(self, mocker):
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, exc=LLMError("x")), "p")
        with pytest.raises(LLMError):
            await ex.extract("text")

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


class TestAsyncLLMEntityExtractorValidation:
    @staticmethod
    def _validator(mocker, accepts):
        validator = mocker.Mock(spec=RecordValidator)
        validator.is_valid.side_effect = accepts
        return validator

    @pytest.mark.asyncio
    async def test_rejected_entities_are_dropped_and_logged_by_label(self, mocker):
        payload = {"items": [{"name": "A", "ra": 10}, {"name": "B", "ra": 400}]}
        lines: list[str] = []
        ex = AsyncLLMEntityExtractor(
            _async_llm(mocker, payload),
            "p",
            validator=NumericRangeValidator({"ra": (0.0, 360.0)}),
            logger=lines.append,
            label_field="name",
        )
        assert await ex.extract("text") == [{"name": "A", "ra": 10}]
        assert lines == ["Entity rejected by validation: 'B'"]

    @pytest.mark.asyncio
    async def test_rejection_without_label_field_logs_the_position(self, mocker):
        lines: list[str] = []
        validator = self._validator(mocker, lambda entity: entity["ok"])
        payload = {"items": [{"ok": True}, {"ok": False}]}
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, payload), "p", validator=validator, logger=lines.append)
        assert await ex.extract("text") == [{"ok": True}]
        assert lines == ["Entity rejected by validation: entity 1"]

    @pytest.mark.asyncio
    async def test_validator_applies_to_an_unwrapped_single_key_response(self, mocker):
        validator = self._validator(mocker, lambda _entity: False)
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, {"other": [{"name": "A"}]}), "p", validator=validator)
        assert await ex.extract("text") == []

    @pytest.mark.asyncio
    async def test_every_entity_is_checked(self, mocker):
        validator = self._validator(mocker, lambda _entity: True)
        payload = {"items": [{"n": 1}, {"n": 2}, {"n": 3}]}
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, payload), "p", validator=validator)
        assert await ex.extract("text") == payload["items"]
        assert validator.is_valid.call_count == 3


class TestAsyncLLMEntityExtractorTokenTruncation:
    @pytest.mark.asyncio
    async def test_token_truncation_used_when_available(self, mocker):
        mocker.patch(
            "sci_etl_core.llm.extraction_async.truncate_to_tokens",
            return_value="token-truncated",
        )
        client = _async_llm(mocker, {"items": []})
        ex = AsyncLLMEntityExtractor(client, "p", result_key="items", max_tokens=32)
        await ex.extract("some long body text")
        assert client.complete_json.call_args[0][1] == "token-truncated"


class TestAsyncCancellationPropagation:
    @pytest.mark.asyncio
    async def test_entity_extractor_reraises_cancelled_error(self, mocker):
        ex = AsyncLLMEntityExtractor(_async_llm(mocker, exc=asyncio.CancelledError()), "p")
        with pytest.raises(asyncio.CancelledError):
            await ex.extract("body text")

    @pytest.mark.asyncio
    async def test_relevance_filter_reraises_cancelled_error(self, mocker):
        f = AsyncLLMRelevanceFilter(_async_llm(mocker, exc=asyncio.CancelledError()), "p")
        with pytest.raises(asyncio.CancelledError):
            await f.is_relevant(RawRecord("1", "t", "abstract"))
