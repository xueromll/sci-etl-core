from __future__ import annotations

import threading

import pytest

from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.extraction_async import AsyncLLMEntityExtractor
from sci_etl_core.parsers.base import Parser


def _message(mocker, content):
    choice = mocker.Mock()
    choice.message.content = content
    response = mocker.Mock()
    response.choices = [choice]
    return response


def _client_returning(mocker, result):
    client = mocker.Mock(spec=AsyncLLMClient)
    client.complete_json = mocker.AsyncMock(return_value=result)
    return client


class TestCompleteJsonRequiresAnObject:
    @pytest.mark.parametrize("content", ["[1, 2]", "null", '"text"', "42"])
    @pytest.mark.asyncio
    async def test_json_that_is_not_an_object_raises(self, mocker, content):
        from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient

        instance = mocker.patch("sci_etl_core.llm.openai_compatible_async.AsyncOpenAI").return_value
        instance.chat.completions.create = mocker.AsyncMock(return_value=_message(mocker, content))
        client = AsyncOpenAICompatibleClient(api_key="k", base_url="u", model="m", sleep=mocker.AsyncMock())
        with pytest.raises(LLMError, match="not an object"):
            await client.complete_json("s", "u")


class TestEntityShapes:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"items": None}, []),
            ({"items": {"name": "A"}}, [{"name": "A"}]),
            ({"items": []}, []),
            ({"result": [{"name": "B"}]}, [{"name": "B"}]),
        ],
    )
    @pytest.mark.asyncio
    async def test_accepted_shapes(self, mocker, payload, expected):
        extractor = AsyncLLMEntityExtractor(_client_returning(mocker, payload), "p")
        assert await extractor.extract("text") == expected

    @pytest.mark.parametrize(
        "payload",
        [
            {"items": "Object A"},
            {"items": ["A", "B"]},
            {"items": [{"name": "A"}, "B"]},
            {"items": 3},
            {"result": "Object A"},
        ],
    )
    @pytest.mark.asyncio
    async def test_malformed_entity_lists_raise(self, mocker, payload):
        extractor = AsyncLLMEntityExtractor(_client_returning(mocker, payload), "p")
        with pytest.raises(LLMError, match="list of entity objects"):
            await extractor.extract("text")

    @pytest.mark.asyncio
    async def test_non_object_result_from_a_custom_client_raises(self, mocker):
        extractor = AsyncLLMEntityExtractor(_client_returning(mocker, [{"name": "A"}]), "p")
        with pytest.raises(LLMError, match="not a JSON object"):
            await extractor.extract("text")

    @pytest.mark.asyncio
    async def test_html_preparation_runs_off_the_event_loop_thread(self, mocker):
        parser_threads: list[int] = []

        class RecordingParser(Parser):
            def extract_text(self, content: bytes) -> str:
                parser_threads.append(threading.get_ident())
                return "stripped"

        client = _client_returning(mocker, {"items": []})
        extractor = AsyncLLMEntityExtractor(client, "p", html_parser=RecordingParser())
        await extractor.extract("<html><body>x</body></html>")
        assert parser_threads
        assert parser_threads[0] != threading.get_ident()
        assert client.complete_json.await_args.args[1] == "stripped"
