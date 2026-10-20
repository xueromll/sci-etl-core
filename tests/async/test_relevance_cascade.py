from __future__ import annotations

import asyncio

import pytest

from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.exceptions import EmbeddingError, LLMError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.relevance_async import AsyncLLMRelevanceFilter, AsyncRelevanceFilter
from sci_etl_core.llm.relevance_cascade import AsyncCascadingRelevanceFilter
from sci_etl_core.llm.relevance_embedding_async import AsyncEmbeddingRelevanceFilter
from sci_etl_core.models import RawRecord

_RECORD = RawRecord(record_id="a", title="T", abstract="A")


class _VerdictFilter(AsyncRelevanceFilter):
    def __init__(self, name: str, verdict: bool, log: list[str]) -> None:
        self._name = name
        self._verdict = verdict
        self._log = log

    async def is_relevant(self, record):
        self._log.append(self._name)
        return self._verdict


class _RaisingFilter(AsyncRelevanceFilter):
    def __init__(self, name: str, error: BaseException, log: list[str]) -> None:
        self._name = name
        self._error = error
        self._log = log

    async def is_relevant(self, record):
        self._log.append(self._name)
        raise self._error


class _RecordFilter(AsyncRelevanceFilter):
    def __init__(self, kept: set[str]) -> None:
        self._kept = kept

    async def is_relevant(self, record):
        await asyncio.sleep(0)
        return record.record_id in self._kept


class _TableEmbedder(AsyncEmbedder):
    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = table

    async def embed(self, texts):
        return [self._table[text] for text in texts]


class TestAsyncCascadingRelevanceFilter:
    def test_requires_at_least_one_filter(self):
        with pytest.raises(ValueError, match="AsyncCascadingRelevanceFilter needs at least one filter"):
            AsyncCascadingRelevanceFilter()

    @pytest.mark.asyncio
    async def test_single_filter_verdict_is_returned(self):
        log: list[str] = []
        assert await AsyncCascadingRelevanceFilter(_VerdictFilter("a", True, log)).is_relevant(_RECORD) is True
        assert await AsyncCascadingRelevanceFilter(_VerdictFilter("b", False, log)).is_relevant(_RECORD) is False
        assert log == ["a", "b"]

    @pytest.mark.asyncio
    async def test_all_filters_accept_runs_every_filter_in_order(self):
        log: list[str] = []
        cascade = AsyncCascadingRelevanceFilter(
            _VerdictFilter("first", True, log),
            _VerdictFilter("second", True, log),
            _VerdictFilter("third", True, log),
        )
        assert await cascade.is_relevant(_RECORD) is True
        assert log == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_first_rejection_stops_the_cascade(self):
        log: list[str] = []
        cascade = AsyncCascadingRelevanceFilter(
            _VerdictFilter("first", True, log),
            _VerdictFilter("second", False, log),
            _VerdictFilter("third", True, log),
        )
        assert await cascade.is_relevant(_RECORD) is False
        assert log == ["first", "second"]

    @pytest.mark.asyncio
    async def test_rejection_by_the_first_filter_calls_no_other(self):
        log: list[str] = []
        cascade = AsyncCascadingRelevanceFilter(
            _VerdictFilter("first", False, log), _RaisingFilter("second", LLMError("unused"), log)
        )
        assert await cascade.is_relevant(_RECORD) is False
        assert log == ["first"]

    @pytest.mark.asyncio
    async def test_filter_error_propagates_and_later_filters_are_not_called(self):
        log: list[str] = []
        error = LLMError("down")
        cascade = AsyncCascadingRelevanceFilter(
            _VerdictFilter("first", True, log),
            _RaisingFilter("second", error, log),
            _VerdictFilter("third", True, log),
        )
        with pytest.raises(LLMError, match="down") as caught:
            await cascade.is_relevant(_RECORD)
        assert caught.value is error
        assert log == ["first", "second"]

    @pytest.mark.asyncio
    async def test_cancellation_propagates_and_later_filters_are_not_called(self):
        log: list[str] = []
        cascade = AsyncCascadingRelevanceFilter(
            _RaisingFilter("first", asyncio.CancelledError(), log), _VerdictFilter("second", True, log)
        )
        with pytest.raises(asyncio.CancelledError):
            await cascade.is_relevant(_RECORD)
        assert log == ["first"]

    @pytest.mark.asyncio
    async def test_concurrent_records_get_independent_verdicts(self):
        cascade = AsyncCascadingRelevanceFilter(_RecordFilter({"a", "b", "c"}), _RecordFilter({"b", "c", "d"}))
        records = [RawRecord(record_id=record_id, title="T", abstract="A") for record_id in "abcde"]
        verdicts = await asyncio.gather(*(cascade.is_relevant(record) for record in records))
        assert verdicts == [False, True, True, False, False]

    @pytest.mark.asyncio
    async def test_embedding_rejection_spares_the_llm_call(self, mocker):
        llm = mocker.AsyncMock(spec=AsyncLLMClient)
        llm.complete_json.return_value = {"relevant": True}
        embedder = _TableEmbedder({"concept": [1.0, 0.0], "T\nA": [1.0, 0.0], "T\nB": [0.0, 1.0]})
        cascade = AsyncCascadingRelevanceFilter(
            AsyncEmbeddingRelevanceFilter(embedder, ["concept"]), AsyncLLMRelevanceFilter(llm, "prompt")
        )
        assert await cascade.is_relevant(RawRecord(record_id="b", title="T", abstract="B")) is False
        llm.complete_json.assert_not_awaited()
        assert await cascade.is_relevant(_RECORD) is True
        llm.complete_json.assert_awaited_once_with("prompt", "Title: T\nAbstract: A", 20)

    @pytest.mark.asyncio
    async def test_fail_closed_inner_fault_raises_instead_of_rejecting(self):
        class _DownEmbedder(AsyncEmbedder):
            async def embed(self, texts):
                raise EmbeddingError("embedder down")

        log: list[str] = []
        cascade = AsyncCascadingRelevanceFilter(
            AsyncEmbeddingRelevanceFilter(_DownEmbedder(), ["concept"], default_on_error=False),
            _VerdictFilter("llm", True, log),
        )
        with pytest.raises(EmbeddingError, match="embedder down"):
            await cascade.is_relevant(_RECORD)
        assert log == []
