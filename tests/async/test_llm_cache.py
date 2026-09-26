from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing, suppress
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sci_etl_core.exceptions import LLMCacheError, LLMError
from sci_etl_core.llm import (
    AsyncLLMClient,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncLLMResponseCache,
    AsyncSqliteLLMResponseCache,
    CacheStats,
    CachingLLMClient,
    InMemoryLLMResponseCache,
    response_cache_key,
)
from sci_etl_core.models import RawRecord, TokenUsage


class CountingClient(AsyncLLMClient):
    def __init__(self, response=None, error=None, model="m-1") -> None:
        self.model = model
        self.calls: list[tuple[str, str, int | None]] = []
        self._response = response if response is not None else {"items": [{"name": "A"}]}
        self._error = error
        self._usage = TokenUsage()

    @property
    def usage(self) -> TokenUsage:
        return self._usage

    async def complete_json(self, system_prompt, user_content, timeout=None):  # noqa: ASYNC109
        self.calls.append((system_prompt, user_content, timeout))
        self._usage.requests += 1
        if self._error is not None:
            raise self._error
        return dict(self._response)


class BrokenCache(AsyncLLMResponseCache):
    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.inner = InMemoryLLMResponseCache()

    async def get(self, key):
        if "get" in self.failing:
            raise LLMCacheError("unreadable")
        return await self.inner.get(key)

    async def set(self, key, response):
        if "set" in self.failing:
            raise OSError("disk full")
        await self.inner.set(key, response)

    async def clear(self):
        await self.inner.clear()


class TestResponseCacheKey:
    def test_is_a_sha256_hex_digest(self):
        key = response_cache_key("m", "system", "user")
        assert len(key) == 64
        assert int(key, 16) >= 0

    @given(st.text(), st.text(min_size=1), st.text(min_size=1))
    def test_moving_text_between_the_prompts_changes_the_key(self, model, first, second):
        assert response_cache_key(model, first + second, "") != response_cache_key(model, first, second)

    def test_model_and_each_prompt_change_the_key(self):
        keys = {
            response_cache_key("m", "s", "u"),
            response_cache_key("n", "s", "u"),
            response_cache_key("m", "t", "u"),
            response_cache_key("m", "s", "v"),
        }
        assert len(keys) == 4

    def test_base_url_and_temperature_change_the_key(self):
        keys = {
            response_cache_key("m", "s", "u"),
            response_cache_key("m", "s", "u", base_url="https://a"),
            response_cache_key("m", "s", "u", base_url="https://b"),
            response_cache_key("m", "s", "u", temperature=0.0),
            response_cache_key("m", "s", "u", temperature=0.7),
        }
        assert len(keys) == 5

    def test_an_integer_temperature_keys_like_the_equal_float(self):
        assert response_cache_key("m", "s", "u", temperature=0) == response_cache_key("m", "s", "u", temperature=0.0)

    def test_keys_written_by_0_5_0_are_not_reused(self):
        old = json.dumps(["m", "s", "u"], ensure_ascii=False, separators=(",", ":"))
        assert response_cache_key("m", "s", "u") != hashlib.sha256(old.encode("utf-8")).hexdigest()


class TestInMemoryLLMResponseCache:
    @pytest.mark.asyncio
    async def test_round_trip_and_miss(self):
        cache = InMemoryLLMResponseCache()
        assert await cache.get("k") is None
        await cache.set("k", {"relevant": True})
        assert await cache.get("k") == {"relevant": True}

    @pytest.mark.asyncio
    async def test_returned_responses_are_copies(self):
        cache = InMemoryLLMResponseCache()
        original = {"items": [1]}
        await cache.set("k", original)
        original["items"].append(2)
        (await cache.get("k"))["items"].append(3)
        assert await cache.get("k") == {"items": [1]}

    @pytest.mark.asyncio
    async def test_evicts_the_least_recently_used_entry(self):
        cache = InMemoryLLMResponseCache(max_entries=2)
        await cache.set("a", {"n": 1})
        await cache.set("b", {"n": 2})
        await cache.get("a")
        await cache.set("c", {"n": 3})
        assert await cache.get("b") is None
        assert await cache.get("a") == {"n": 1}
        assert len(cache) == 2

    @pytest.mark.asyncio
    async def test_delete_removes_one_entry_and_ignores_a_missing_key(self):
        cache = InMemoryLLMResponseCache()
        await cache.set("a", {"x": 1})
        await cache.set("b", {"x": 2})
        await cache.delete("a")
        await cache.delete("missing")
        assert await cache.get("a") is None
        assert await cache.get("b") == {"x": 2}

    @pytest.mark.asyncio
    async def test_clear_empties_the_cache(self):
        cache = InMemoryLLMResponseCache()
        await cache.set("a", {})
        await cache.clear()
        assert len(cache) == 0

    @pytest.mark.parametrize("max_entries", [0, -1])
    def test_rejects_a_non_positive_bound(self, max_entries):
        with pytest.raises(ValueError, match="positive"):
            InMemoryLLMResponseCache(max_entries=max_entries)


class TestAsyncSqliteLLMResponseCache:
    @pytest.mark.asyncio
    async def test_responses_survive_a_new_instance(self, tmp_path):
        path = tmp_path / "nested" / "cache.db"
        stamp = datetime(2026, 9, 16, tzinfo=UTC)
        first = AsyncSqliteLLMResponseCache(path, now=lambda: stamp)
        await first.set("k", {"relevant": False})
        await first.set("k", {"relevant": True})
        await first.aclose()
        second = AsyncSqliteLLMResponseCache(path)
        try:
            assert await second.get("k") == {"relevant": True}
            assert await second.get("missing") is None
            assert await second.count() == 1
        finally:
            await second.aclose()
        with closing(sqlite3.connect(path)) as reader:
            assert reader.execute("SELECT created_at FROM llm_responses").fetchone()[0] == stamp.isoformat()

    @pytest.mark.asyncio
    async def test_delete_removes_one_response(self, tmp_path):
        cache = AsyncSqliteLLMResponseCache(tmp_path / "llm.db")
        await cache.set("a", {"x": 1})
        await cache.set("b", {"x": 2})
        await cache.delete("a")
        await cache.delete("missing")
        assert await cache.get("a") is None
        assert await cache.count() == 1
        await cache.aclose()

    @pytest.mark.asyncio
    async def test_clear_removes_every_response(self, tmp_path):
        cache = AsyncSqliteLLMResponseCache(tmp_path / "cache.db")
        try:
            await cache.set("a", {})
            await cache.set("b", {})
            await cache.clear()
            assert await cache.count() == 0
        finally:
            await cache.aclose()

    @pytest.mark.asyncio
    async def test_a_file_that_is_not_a_database_raises_a_cache_error(self, tmp_path):
        path = tmp_path / "cache.db"
        path.write_bytes(b"not a database, just some bytes that are long enough to matter" * 4)
        cache = AsyncSqliteLLMResponseCache(path)
        try:
            with pytest.raises(LLMCacheError, match="Failed to"):
                await cache.get("k")
        finally:
            await cache.aclose()

    @pytest.mark.parametrize(("stored", "message"), [("{not json", "not valid JSON"), ("[1]", "not a JSON object")])
    @pytest.mark.asyncio
    async def test_a_corrupt_entry_raises_a_cache_error(self, tmp_path, stored, message):
        path = tmp_path / "cache.db"
        cache = AsyncSqliteLLMResponseCache(path)
        try:
            await cache.set("k", {})
            await cache.aclose()
            with closing(sqlite3.connect(path, isolation_level=None)) as writer:
                writer.execute("UPDATE llm_responses SET response = ?", (stored,))
            with pytest.raises(LLMCacheError, match=message):
                await cache.get("k")
        finally:
            await cache.aclose()


class TestCachingLLMClient:
    @pytest.mark.asyncio
    async def test_a_repeated_request_is_served_from_the_cache(self):
        inner = CountingClient()
        client = CachingLLMClient(inner, InMemoryLLMResponseCache())
        first = await client.complete_json("s", "u", timeout=5)
        second = await client.complete_json("s", "u", timeout=99)
        assert first == second == {"items": [{"name": "A"}]}
        assert inner.calls == [("s", "u", 5)]
        assert client.stats == CacheStats(hits=1, misses=1, faults=0)
        assert client.usage.requests == 1

    @pytest.mark.asyncio
    async def test_different_prompts_or_models_miss(self):
        inner = CountingClient()
        cache = InMemoryLLMResponseCache()
        await CachingLLMClient(inner, cache).complete_json("s", "u")
        await CachingLLMClient(inner, cache).complete_json("s", "other")
        await CachingLLMClient(inner, cache, model="m-1@t0.7").complete_json("s", "u")
        assert len(inner.calls) == 3

    @pytest.mark.asyncio
    async def test_a_failed_completion_is_not_cached(self):
        cache = InMemoryLLMResponseCache()
        failing = CachingLLMClient(CountingClient(error=LLMError("down")), cache)
        with pytest.raises(LLMError):
            await failing.complete_json("s", "u")
        assert len(cache) == 0

    @pytest.mark.parametrize(
        ("failing", "message"),
        [({"get"}, "LLM cache get failed: LLMCacheError('unreadable')"), ({"set"}, "LLM cache set failed: OSError")],
    )
    @pytest.mark.asyncio
    async def test_a_cache_fault_is_logged_and_the_llm_answers(self, failing, message):
        lines: list[str] = []
        inner = CountingClient()
        client = CachingLLMClient(inner, BrokenCache(failing), logger=lines.append)
        assert await client.complete_json("s", "u") == {"items": [{"name": "A"}]}
        assert lines[0].startswith(message)
        assert client.stats.faults == 1
        assert len(inner.calls) == 1

    @pytest.mark.parametrize("operation", ["get", "set"])
    @pytest.mark.asyncio
    async def test_cancellation_inside_the_cache_propagates(self, mocker, operation):
        cache = InMemoryLLMResponseCache()
        mocker.patch.object(cache, operation, side_effect=asyncio.CancelledError)
        client = CachingLLMClient(CountingClient(), cache)
        with pytest.raises(asyncio.CancelledError):
            await client.complete_json("s", "u")

    def test_the_model_defaults_to_the_wrapped_clients(self):
        assert CachingLLMClient(CountingClient(model="gpt-x"), InMemoryLLMResponseCache()).model == "gpt-x"

    @pytest.mark.parametrize("model", [None, ""])
    def test_a_client_without_a_model_name_needs_one(self, model):
        with pytest.raises(ValueError, match="Pass model="):
            CachingLLMClient(CountingClient(model=model), InMemoryLLMResponseCache())

    def test_the_openai_client_exposes_its_model(self, mocker):
        from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient

        mocker.patch("sci_etl_core.llm.openai_compatible_async.AsyncOpenAI")
        client = AsyncOpenAICompatibleClient(api_key="k", base_url="https://x", model="gpt-y")
        assert CachingLLMClient(client, InMemoryLLMResponseCache()).model == "gpt-y"

    def test_the_openai_client_exposes_its_base_url_and_temperature(self, mocker):
        from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient

        mocker.patch("sci_etl_core.llm.openai_compatible_async.AsyncOpenAI")
        client = AsyncOpenAICompatibleClient(api_key="k", base_url="https://x", model="gpt-y", temperature=0.3)
        caching = CachingLLMClient(client, InMemoryLLMResponseCache())
        assert (caching.base_url, caching.temperature) == ("https://x", 0.3)

    @pytest.mark.parametrize(("base_url", "temperature"), [(None, None), (42, True), (b"https://x", "0.2")])
    def test_missing_or_unusable_endpoint_attributes_are_left_out_of_the_key(self, base_url, temperature):
        inner = CountingClient()
        inner.base_url = base_url
        inner.temperature = temperature
        caching = CachingLLMClient(inner, InMemoryLLMResponseCache())
        assert (caching.base_url, caching.temperature) == (None, None)

    @pytest.mark.asyncio
    async def test_a_different_endpoint_or_temperature_misses(self):
        cache = InMemoryLLMResponseCache()
        calls = 0
        for base_url, temperature in [("https://a", 0.0), ("https://b", 0.0), ("https://a", 0.7), ("https://a", 0)]:
            inner = CountingClient()
            inner.base_url = base_url
            inner.temperature = temperature
            await CachingLLMClient(inner, cache).complete_json("s", "u")
            calls += len(inner.calls)
        assert calls == 3

    @pytest.mark.asyncio
    async def test_invalidate_removes_the_response_and_tells_the_wrapped_client(self, mocker):
        inner = CountingClient()
        forwarded = mocker.patch.object(inner, "invalidate", wraps=inner.invalidate)
        client = CachingLLMClient(inner, InMemoryLLMResponseCache())
        await client.complete_json("s", "u")
        await client.invalidate("s", "u")
        await client.complete_json("s", "u")
        assert len(inner.calls) == 2
        forwarded.assert_awaited_once_with("s", "u")

    @pytest.mark.asyncio
    async def test_a_backend_without_delete_is_logged_as_a_fault(self):
        lines: list[str] = []
        client = CachingLLMClient(CountingClient(), BrokenCache(set()), logger=lines.append)
        await client.invalidate("s", "u")
        assert lines == ["LLM cache delete failed: NotImplementedError('BrokenCache does not implement delete')"]
        assert client.stats.faults == 1

    @pytest.mark.asyncio
    async def test_cancellation_inside_delete_propagates(self, mocker):
        cache = InMemoryLLMResponseCache()
        mocker.patch.object(cache, "delete", side_effect=asyncio.CancelledError)
        with pytest.raises(asyncio.CancelledError):
            await CachingLLMClient(CountingClient(), cache).invalidate("s", "u")


class TestRejectedResponsesAreNotReplayed:
    @pytest.mark.parametrize("response", [{"a": [], "b": []}, {}, {"items": "Object A"}])
    @pytest.mark.asyncio
    async def test_a_response_the_extractor_rejects_reaches_the_llm_again(self, response):
        inner = CountingClient(response=response)
        extractor = AsyncLLMEntityExtractor(CachingLLMClient(inner, InMemoryLLMResponseCache()), "p")
        for _ in range(2):
            with pytest.raises(LLMError):
                await extractor.extract("paper text")
        assert len(inner.calls) == 2

    @pytest.mark.asyncio
    async def test_a_response_the_extractor_accepts_stays_cached(self):
        inner = CountingClient(response={"items": [{"name": "A"}]})
        extractor = AsyncLLMEntityExtractor(CachingLLMClient(inner, InMemoryLLMResponseCache()), "p")
        assert await extractor.extract("paper text") == await extractor.extract("paper text") == [{"name": "A"}]
        assert len(inner.calls) == 1

    @pytest.mark.parametrize("default_on_error", [True, False])
    @pytest.mark.asyncio
    async def test_a_relevance_response_without_a_clear_verdict_reaches_the_llm_again(self, default_on_error):
        inner = CountingClient(response={"relevant": "maybe"})
        relevance = AsyncLLMRelevanceFilter(
            CachingLLMClient(inner, InMemoryLLMResponseCache()), "p", default_on_error=default_on_error
        )
        record = RawRecord(record_id="1", title="t", abstract="abstract")
        for _ in range(2):
            with suppress(LLMError):
                await relevance.is_relevant(record)
        assert len(inner.calls) == 2

    @pytest.mark.asyncio
    async def test_a_clear_relevance_verdict_stays_cached(self):
        inner = CountingClient(response={"relevant": False})
        relevance = AsyncLLMRelevanceFilter(CachingLLMClient(inner, InMemoryLLMResponseCache()), "p")
        record = RawRecord(record_id="1", title="t", abstract="abstract")
        assert await relevance.is_relevant(record) is await relevance.is_relevant(record) is False
        assert len(inner.calls) == 1
