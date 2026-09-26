from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from sci_etl_core.claims.models import ExtractionStamp, content_hash
from sci_etl_core.claims.rejections import InMemoryRejectionStore, rejection_id
from sci_etl_core.exceptions import ClaimStoreError, LLMError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.cache_async import CachingLLMClient, InMemoryLLMResponseCache, response_cache_key
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor, AsyncLLMEntityExtractor, entity_list_schema
from sci_etl_core.models import RawRecord
from sci_etl_core.processors.validation import NumericRangeValidator, Violation

RECORD = RawRecord(record_id="2401.00001", title="t", abstract="a")
FIXED = datetime(2026, 9, 26, tzinfo=UTC)


class Galaxy(BaseModel):
    name: str
    radius_kpc: float | None = None


class Nested(BaseModel):
    galaxy: Galaxy


class ScriptedClient(AsyncLLMClient):
    def __init__(self, answer: Any, model: str = "m-1") -> None:
        self.answer = answer
        self.model = model
        self.json_calls: list[str] = []
        self.structured_calls: list[tuple[str, dict[str, Any]]] = []
        self.invalidated: list[tuple[str, dict[str, Any] | None]] = []

    async def complete_json(self, system_prompt, user_content, timeout=None):  # noqa: ASYNC109
        self.json_calls.append(user_content)
        return self.answer

    async def complete_structured(self, system_prompt, user_content, schema, timeout=None):  # noqa: ASYNC109
        self.structured_calls.append((user_content, dict(schema)))
        return self.answer

    async def invalidate(self, system_prompt, user_content, *, schema=None):
        self.invalidated.append((user_content, schema))


class JsonOnlyClient(AsyncLLMClient):
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls = 0

    async def complete_json(self, system_prompt, user_content, timeout=None):  # noqa: ASYNC109
        self.calls += 1
        return self.answer


class TestEntityListSchema:
    def test_wraps_the_entity_schema_in_a_list_under_the_result_key(self):
        schema = entity_list_schema(Galaxy, "galaxies")

        assert schema["required"] == ["galaxies"]
        assert schema["properties"]["galaxies"]["items"]["properties"]["name"] == {"title": "Name", "type": "string"}
        assert "$defs" not in schema

    def test_moves_definitions_to_the_root_so_references_resolve(self):
        schema = entity_list_schema(Nested, "items")

        assert "Galaxy" in schema["$defs"]
        assert "$defs" not in schema["properties"]["items"]["items"]

    def test_accepts_a_json_schema_mapping(self):
        schema = entity_list_schema({"type": "object"}, "items")

        assert schema["properties"]["items"]["items"] == {"type": "object"}


class TestTypedExtraction:
    @pytest.mark.asyncio
    async def test_entities_are_model_instances_requested_as_structured_output(self):
        client = ScriptedClient({"items": [{"name": "DF2", "radius_kpc": 2.2}]})
        extractor = AsyncLLMEntityExtractor(client, "prompt", schema=Galaxy)

        entities = await extractor.extract_record(RECORD, "text")

        assert entities == [Galaxy(name="DF2", radius_kpc=2.2)]
        assert client.structured_calls == [("text", extractor.answer_schema)]
        assert client.json_calls == []

    @pytest.mark.asyncio
    async def test_a_client_without_structured_output_answers_in_json_mode_and_is_still_validated(self):
        client = JsonOnlyClient({"items": [{"name": "DF2"}, {"radius_kpc": 1.0}]})
        extractor = AsyncLLMEntityExtractor(client, "prompt", schema=Galaxy)

        assert await extractor.extract("text") == [Galaxy(name="DF2")]
        assert client.calls == 1

    @pytest.mark.asyncio
    async def test_schema_failures_are_rejected_with_the_field_and_reason(self, caplog):
        client = ScriptedClient({"items": [{"name": "DF2", "radius_kpc": "large"}]})
        extractor = AsyncLLMEntityExtractor(client, "prompt", schema=Galaxy, label_field="name")

        with caplog.at_level("INFO", logger="sci_etl_core.llm.extraction_async"):
            assert await extractor.extract("text") == []

        assert caplog.messages[0].startswith("Entity rejected by validation: 'DF2' (radius_kpc: ")

    @pytest.mark.asyncio
    async def test_validator_sees_the_validated_entity_as_a_dict(self):
        client = ScriptedClient({"items": [{"name": "DF2", "radius_kpc": "40"}, {"name": "DF4", "radius_kpc": 1}]})
        extractor = AsyncLLMEntityExtractor(
            client, "prompt", schema=Galaxy, validator=NumericRangeValidator({"radius_kpc": (0.1, 20.0)})
        )

        assert await extractor.extract("text") == [Galaxy(name="DF4", radius_kpc=1.0)]

    @pytest.mark.asyncio
    async def test_a_rejected_answer_is_invalidated_with_its_schema(self):
        client = ScriptedClient({"a": [], "b": []})
        extractor = AsyncLLMEntityExtractor(client, "prompt", schema=Galaxy)

        with pytest.raises(LLMError):
            await extractor.extract("text")

        assert client.invalidated == [("text", extractor.answer_schema)]

    @pytest.mark.asyncio
    async def test_an_untyped_rejected_answer_is_invalidated_without_a_schema(self):
        client = ScriptedClient({"a": [], "b": []})
        extractor = AsyncLLMEntityExtractor(client, "prompt")

        with pytest.raises(LLMError):
            await extractor.extract("text")

        assert client.invalidated == [("text", None)]


class TestRejections:
    @pytest.mark.asyncio
    async def test_rejected_entities_are_stored_with_record_violations_and_stamp(self):
        store = InMemoryRejectionStore()
        client = ScriptedClient({"items": [{"name": "A", "ra": 400, "quote": "ra = 400"}, {"name": "B", "ra": 1}]})
        extractor = AsyncLLMEntityExtractor(
            client, "prompt", validator=NumericRangeValidator({"ra": (0.0, 360.0)}), rejections=store, now=lambda: FIXED
        )

        assert await extractor.extract_record(RECORD, "text") == [{"name": "B", "ra": 1}]

        [entry] = await store.unresolved()
        violation = Violation(code="out-of-range", field="ra", severity="error", message="ra is 400, outside [0, 360]")
        assert entry.record_id == RECORD.record_id
        assert entry.entity == {"name": "A", "ra": 400, "quote": "ra = 400"}
        assert entry.violations == (violation,)
        assert entry.stamp == extractor.stamp
        assert entry.quote == "ra = 400"
        assert entry.created_at == FIXED.isoformat()
        assert entry.entry_id == rejection_id(RECORD.record_id, entry.entity, (violation,), extractor.stamp)

    @pytest.mark.asyncio
    async def test_extracting_the_record_again_keeps_one_entry(self):
        store = InMemoryRejectionStore()
        client = ScriptedClient({"items": [{"name": "A", "ra": 400}]})
        extractor = AsyncLLMEntityExtractor(
            client, "prompt", validator=NumericRangeValidator({"ra": (0.0, 360.0)}), rejections=store
        )

        await extractor.extract_record(RECORD, "text")
        await extractor.extract_record(RECORD, "text")

        assert await store.count() == 1

    @pytest.mark.asyncio
    async def test_extract_without_a_record_files_rejections_under_an_empty_id(self):
        store = InMemoryRejectionStore()
        client = ScriptedClient({"items": [{"ra": 400}]})
        extractor = AsyncLLMEntityExtractor(
            client, "prompt", validator=NumericRangeValidator({"ra": (0.0, 360.0)}), rejections=store
        )

        await extractor.extract("text")

        assert [entry.record_id for entry in await store.unresolved()] == [""]

    @pytest.mark.asyncio
    async def test_a_rejection_store_fault_fails_the_extraction(self, mocker):
        store = InMemoryRejectionStore()
        mocker.patch.object(store, "put", side_effect=ClaimStoreError("disk full"))
        client = ScriptedClient({"items": [{"ra": 400}]})
        extractor = AsyncLLMEntityExtractor(
            client, "prompt", validator=NumericRangeValidator({"ra": (0.0, 360.0)}), rejections=store
        )

        with pytest.raises(ClaimStoreError):
            await extractor.extract_record(RECORD, "text")

    @pytest.mark.asyncio
    async def test_nothing_is_stored_when_every_entity_is_kept(self, mocker):
        store = InMemoryRejectionStore()
        put = mocker.spy(store, "put")
        extractor = AsyncLLMEntityExtractor(ScriptedClient({"items": [{"ra": 1}]}), "prompt", rejections=store)

        await extractor.extract_record(RECORD, "text")

        put.assert_not_called()


class TestStamp:
    def test_stamp_names_the_model_prompt_schema_and_library(self):
        extractor = AsyncLLMEntityExtractor(ScriptedClient({}), "prompt", schema=Galaxy)

        stamp = extractor.stamp

        assert stamp.model == "m-1"
        assert stamp.prompt_hash == content_hash("prompt")
        assert stamp.schema_hash == content_hash(extractor.answer_schema)
        assert stamp.extractor_version.startswith("sci-etl-core")

    @pytest.mark.parametrize("model", [None, 42])
    def test_a_client_without_a_model_name_stamps_an_empty_model(self, model):
        client = ScriptedClient({}, model=model)

        assert AsyncLLMEntityExtractor(client, "prompt").stamp.model == ""

    def test_an_untyped_extractor_has_an_empty_schema_hash(self):
        assert AsyncLLMEntityExtractor(ScriptedClient({}), "prompt").stamp.schema_hash == ""

    def test_stamp_round_trips_through_a_dict(self):
        stamp = ExtractionStamp(model="m", prompt_hash="p", schema_hash="s", extractor_version="v")

        assert ExtractionStamp.from_dict(stamp.to_dict()) == stamp


class TestRecordAwareness:
    @pytest.mark.asyncio
    async def test_extract_record_defaults_to_extract(self):
        class TextOnly(AsyncEntityExtractor[str]):
            async def extract(self, text):
                return [f"seen {text}"]

        assert TextOnly.requires_record is False
        assert await TextOnly().extract_record(RECORD, "body") == ["seen body"]


class TestPrepare:
    def test_markup_is_stripped_before_truncation(self):
        extractor = AsyncLLMEntityExtractor(ScriptedClient({}), "prompt", max_chars=5)

        assert extractor.prepare(b"<p>Hello world</p>") == "Hello"

    @given(st.text(alphabet=st.characters(blacklist_characters="<", blacklist_categories=["Cs"])))
    def test_preparing_prepared_plain_text_changes_nothing(self, text):
        extractor = AsyncLLMEntityExtractor(ScriptedClient({}), "prompt", max_chars=50)

        once = extractor.prepare(text)

        assert extractor.prepare(once) == once


class StructuredClient(AsyncLLMClient):
    model = "m-1"

    def __init__(self) -> None:
        self.structured = 0
        self.invalidated: list[Any] = []

    async def complete_json(self, system_prompt, user_content, timeout=None):  # noqa: ASYNC109
        return {"items": []}

    async def complete_structured(self, system_prompt, user_content, schema, timeout=None):  # noqa: ASYNC109
        self.structured += 1
        return {"items": [{"name": "DF2"}]}

    async def invalidate(self, system_prompt, user_content, *, schema=None):
        self.invalidated.append(schema)


class TestStructuredCaching:
    def test_the_key_without_schema_or_variant_is_unchanged_from_0_5_1(self):
        assert response_cache_key("m", "s", "u") == "80a46c472f51e88583f148f2e6eecf036b1dc9337cc4e2b6aefbe4d2ccc423bb"
        assert response_cache_key(
            "m", "s", "u", base_url="https://x", temperature=0.2, response_format={"type": "json_object"}
        ) == "626214105a9a6b002ec294d404cc3329a3c9360dd437707eb20e91dc13d946fa"

    def test_schema_and_variant_join_the_key_and_key_order_does_not_matter(self):
        plain = response_cache_key("m", "s", "u")
        first = response_cache_key("m", "s", "u", schema={"a": 1, "b": 2})
        reordered = response_cache_key("m", "s", "u", schema={"b": 2, "a": 1})
        other = response_cache_key("m", "s", "u", schema={"a": 2})
        variant = response_cache_key("m", "s", "u", variant="sample-2")

        assert first == reordered
        assert len({plain, first, other, variant}) == 4

    @pytest.mark.asyncio
    async def test_structured_answers_are_cached_per_schema(self):
        inner = StructuredClient()
        client = CachingLLMClient(inner, InMemoryLLMResponseCache())

        await client.complete_structured("s", "u", {"x": 1})
        await client.complete_structured("s", "u", {"x": 1})
        await client.complete_structured("s", "u", {"x": 2})

        assert inner.structured == 2

    @pytest.mark.asyncio
    async def test_a_different_variant_misses(self):
        inner = StructuredClient()
        cache = InMemoryLLMResponseCache()

        await CachingLLMClient(inner, cache).complete_structured("s", "u", {"x": 1})
        await CachingLLMClient(inner, cache, variant="second").complete_structured("s", "u", {"x": 1})

        assert inner.structured == 2

    @pytest.mark.asyncio
    async def test_invalidating_a_structured_answer_removes_it_and_tells_the_wrapped_client(self):
        inner = StructuredClient()
        client = CachingLLMClient(inner, InMemoryLLMResponseCache())

        await client.complete_structured("s", "u", {"x": 1})
        await client.invalidate("s", "u", schema={"x": 1})
        await client.complete_structured("s", "u", {"x": 1})

        assert inner.structured == 2
        assert inner.invalidated == [{"x": 1}]

    @pytest.mark.asyncio
    async def test_default_complete_structured_uses_json_mode(self):
        client = JsonOnlyClient({"items": []})

        assert await client.complete_structured("s", "u", {"x": 1}) == {"items": []}
        assert client.calls == 1


class TestOpenAIStructuredOutput:
    @pytest.fixture
    def patched(self, mocker):
        instance = mocker.patch("sci_etl_core.llm.openai_compatible_async.AsyncOpenAI").return_value
        choice = mocker.Mock()
        choice.message.content = '{"items": []}'
        instance.chat.completions.create = mocker.AsyncMock(return_value=mocker.Mock(choices=[choice]))
        return instance

    def _make(self, **kwargs):
        from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient

        return AsyncOpenAICompatibleClient(api_key="k", base_url="u", model="m", **kwargs)

    @pytest.mark.asyncio
    async def test_structured_output_sends_the_schema_as_a_json_schema_format(self, patched):
        client = self._make(structured_output=True)

        await client.complete_structured("s", "u", {"type": "object"})

        assert client.structured_output is True
        assert patched.chat.completions.create.call_args.kwargs["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": {"type": "object"}},
        }

    @pytest.mark.asyncio
    async def test_without_structured_output_the_request_uses_json_mode(self, patched):
        await self._make().complete_structured("s", "u", {"type": "object"})

        assert patched.chat.completions.create.call_args.kwargs["response_format"] == {"type": "json_object"}

    def test_from_config_reads_structured_output(self):
        from sci_etl_core.config import LLMConfig
        from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient

        client = AsyncOpenAICompatibleClient.from_config(LLMConfig(api_key="k", structured_output=True))

        assert client.structured_output is True
