from __future__ import annotations

import asyncio
import itertools

import pytest

from sci_etl_core.exceptions import EmbeddingStoreError, LLMError, PipelineAborted, UpstreamError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord, TokenUsage
from sci_etl_core.observability import (
    PageFetched,
    PageFinished,
    RecordFinished,
    RunFinished,
    RunMetrics,
    RunStarted,
)
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.signals import ShutdownSignal
from sci_etl_core.state.async_base import AsyncStateManager


def _records(ids):
    return [RawRecord(record_id=record_id, title=f"t-{record_id}", abstract="a") for record_id in ids]


class TickingClock:
    def __init__(self) -> None:
        self._ticks = itertools.count()

    def __call__(self) -> float:
        return float(next(self._ticks))


class MeteredClient:
    def __init__(self, usage: TokenUsage | None) -> None:
        self._usage = usage

    @property
    def usage(self) -> TokenUsage | None:
        return self._usage


def _parts(mocker, pages, *, relevant=lambda record: True, entities=None):
    extractor = mocker.Mock(spec=AsyncExtractor)
    extractor.search = mocker.AsyncMock(return_value=b"<feed/>")
    extractor.parse_listing = mocker.Mock(side_effect=[(page, max(len(page), 1)) for page in pages] + [([], 0)] * 5)
    extractor.fetch_full_text = mocker.AsyncMock(side_effect=lambda record: record.record_id)
    relevance = mocker.Mock(spec=AsyncRelevanceFilter)
    relevance.is_relevant = mocker.AsyncMock(side_effect=relevant)
    entity = mocker.Mock(spec=AsyncEntityExtractor)
    entity.extract = mocker.AsyncMock(side_effect=entities or (lambda text: [{"name": text}]))
    exporter = mocker.Mock(spec=AsyncExporter)
    exporter.export = mocker.AsyncMock()
    state = mocker.Mock(spec=AsyncStateManager)
    state.load_processed_ids = mocker.AsyncMock(return_value=set())
    state.load_metadata = mocker.AsyncMock(return_value=PipelineMetadata())
    state.mark_processed = mocker.AsyncMock()
    state.save_metadata = mocker.AsyncMock()
    state.flush = mocker.AsyncMock()
    return {
        "extractor": extractor,
        "relevance_filter": relevance,
        "entity_extractor": entity,
        "exporter": exporter,
        "state_manager": state,
        "destination": "out.csv",
    }


class TestEvents:
    @pytest.mark.asyncio
    async def test_a_run_emits_events_in_order_with_record_outcomes(self, mocker):
        events = []
        records = _records(["a", "b", "c"])
        parts = _parts(mocker, [records], relevant=lambda record: record.record_id != "b")
        pipeline = AsyncETLPipeline(
            **parts, max_concurrency=1, on_event=events.append, clock=TickingClock(), sleep=mocker.AsyncMock()
        )
        assert await pipeline.run(query="q", page_size=3, total_limit=10) == 2
        kinds = [type(event).__name__ for event in events]
        assert kinds == [
            "RunStarted",
            "PageFetched",
            "RecordFinished",
            "RecordFinished",
            "RecordFinished",
            "PageFinished",
            "PageFetched",
            "RunFinished",
        ]
        assert events[0] == RunStarted("q", 0, 10, False)
        assert events[1] == PageFetched(0, 3, 3)
        outcomes = [(event.record_id, event.outcome, event.entities) for event in events[2:5]]
        assert outcomes == [("a", "processed", 1), ("b", "irrelevant", 0), ("c", "processed", 1)]
        assert all(event.duration_seconds > 0 for event in events[2:5])
        page_finished = events[5]
        assert isinstance(page_finished, PageFinished)
        assert (page_finished.metrics.processed, page_finished.metrics.irrelevant) == (2, 1)

    @pytest.mark.asyncio
    async def test_a_failed_record_carries_its_error(self, mocker):
        events = []
        boom = LLMError("bad")

        def extract(text):
            if text == "b":
                raise boom
            return [{"name": text}]

        parts = _parts(mocker, [_records(["a", "b"])], entities=extract)
        pipeline = AsyncETLPipeline(**parts, on_event=events.append, sleep=mocker.AsyncMock())
        await pipeline.run(query="q", page_size=2, total_limit=2)
        failed = [event for event in events if isinstance(event, RecordFinished) and event.outcome == "failed"]
        assert [(event.record_id, event.error) for event in failed] == [("b", boom)]

    @pytest.mark.asyncio
    async def test_deferred_and_skipped_records_are_reported(self, mocker):
        events = []
        records = [RawRecord(record_id="", title="nameless", abstract="a"), *_records(["a", "b"])]
        parts = _parts(mocker, [records])
        pipeline = AsyncETLPipeline(**parts, max_concurrency=1, on_event=events.append, sleep=mocker.AsyncMock())
        await pipeline.run(query="q", page_size=3, total_limit=1)
        finished = [(event.title, event.outcome) for event in events if isinstance(event, RecordFinished)]
        assert finished == [("nameless", "skipped"), ("t-a", "processed"), ("t-b", "deferred")]
        skipped = next(event for event in events if isinstance(event, RecordFinished))
        assert skipped.duration_seconds == 0.0

    @pytest.mark.asyncio
    async def test_a_failing_handler_is_logged_and_the_run_continues(self, mocker):
        lines: list[str] = []

        def handler(event):
            raise RuntimeError("dashboard offline")

        parts = _parts(mocker, [_records(["a"])])
        pipeline = AsyncETLPipeline(**parts, on_event=handler, logger=lines.append, sleep=mocker.AsyncMock())
        assert await pipeline.run(query="q", page_size=1, total_limit=1) == 1
        assert "Event handler failed: RuntimeError('dashboard offline')" in lines

    @pytest.mark.asyncio
    async def test_without_a_handler_nothing_is_emitted_and_metrics_are_kept(self, mocker):
        parts = _parts(mocker, [_records(["a"])])
        pipeline = AsyncETLPipeline(**parts, sleep=mocker.AsyncMock())
        assert pipeline.last_run_metrics is None
        await pipeline.run(query="q", page_size=1, total_limit=1)
        assert pipeline.last_run_metrics.processed == 1


class TestRunMetrics:
    @pytest.mark.asyncio
    async def test_a_completed_run_counts_pages_records_entities_and_duration(self, mocker):
        parts = _parts(
            mocker,
            [_records(["a", "b"]), _records(["c"])],
            relevant=lambda record: record.record_id != "c",
            entities=lambda text: [{"n": 1}, {"n": 2}],
        )
        pipeline = AsyncETLPipeline(**parts, clock=TickingClock(), sleep=mocker.AsyncMock())
        await pipeline.run(query="q", page_size=2, total_limit=10)
        metrics = pipeline.last_run_metrics
        assert (metrics.pages, metrics.listed) == (3, 3)
        assert (metrics.processed, metrics.irrelevant, metrics.failed) == (2, 1, 0)
        assert metrics.entities_exported == 4
        assert metrics.outcome == "completed"
        assert metrics.duration_seconds > 0
        assert metrics.token_usage is None

    @pytest.mark.asyncio
    async def test_memory_faults_are_counted(self, mocker):
        ingestor = mocker.Mock()
        ingestor.ingest = mocker.AsyncMock(side_effect=EmbeddingStoreError("locked"))
        parts = _parts(mocker, [_records(["a"])])
        pipeline = AsyncETLPipeline(**parts, memory_ingestor=ingestor, sleep=mocker.AsyncMock())
        await pipeline.run(query="q", page_size=1, total_limit=1)
        assert pipeline.last_run_metrics.memory_faults == 1

    @pytest.mark.asyncio
    async def test_token_usage_is_the_difference_across_the_run_summed_over_sources(self, mocker):
        chat_usage = TokenUsage(requests=5, prompt_tokens=100, completion_tokens=10)
        embed_usage = TokenUsage(requests=1, prompt_tokens=7)
        parts = _parts(mocker, [_records(["a"])])

        async def extract(text):
            chat_usage.record(type("U", (), {"prompt_tokens": 30, "completion_tokens": 4})())
            return [{"name": text}]

        parts["entity_extractor"].extract = mocker.AsyncMock(side_effect=extract)
        pipeline = AsyncETLPipeline(
            **parts,
            usage_sources=[MeteredClient(chat_usage), MeteredClient(embed_usage), MeteredClient(None)],
            sleep=mocker.AsyncMock(),
        )
        await pipeline.run(query="q", page_size=1, total_limit=1)
        assert pipeline.last_run_metrics.token_usage == TokenUsage(requests=1, prompt_tokens=30, completion_tokens=4)

    @pytest.mark.parametrize(
        ("failure", "outcome", "raised"),
        [
            (UpstreamError("down"), "aborted", PipelineAborted),
            (RuntimeError("bug"), "failed", RuntimeError),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_failed_run_still_records_metrics_and_emits_run_finished(self, mocker, failure, outcome, raised):
        events = []
        parts = _parts(mocker, [_records(["a"])])
        parts["extractor"].search.side_effect = failure
        pipeline = AsyncETLPipeline(**parts, on_event=events.append, sleep=mocker.AsyncMock())
        with pytest.raises(raised):
            await pipeline.run(query="q", page_size=1, total_limit=1)
        assert pipeline.last_run_metrics.outcome == outcome
        assert isinstance(events[-1], RunFinished)
        assert events[-1].metrics.outcome == outcome

    @pytest.mark.asyncio
    async def test_an_interrupted_run_is_reported_as_interrupted(self, mocker):
        shutdown = ShutdownSignal(signals=())
        shutdown.request()
        parts = _parts(mocker, [_records(["a"])])
        pipeline = AsyncETLPipeline(**parts, shutdown=shutdown, sleep=mocker.AsyncMock())
        with pytest.raises(PipelineAborted):
            await pipeline.run(query="q", page_size=1, total_limit=1)
        assert pipeline.last_run_metrics.outcome == "interrupted"

    @pytest.mark.asyncio
    async def test_a_cancelled_run_is_reported_as_cancelled(self, mocker):
        parts = _parts(mocker, [_records(["a"])])

        async def hang(*_args):
            await asyncio.sleep(30)

        parts["extractor"].search.side_effect = hang
        pipeline = AsyncETLPipeline(**parts, sleep=mocker.AsyncMock())
        run = asyncio.create_task(pipeline.run(query="q", page_size=1, total_limit=1))
        await asyncio.sleep(0.01)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert pipeline.last_run_metrics.outcome == "cancelled"

    @pytest.mark.asyncio
    async def test_each_run_starts_fresh_and_snapshots_are_independent(self, mocker):
        parts = _parts(mocker, [_records(["a"]), _records(["b"])])
        parts["extractor"].parse_listing.side_effect = [
            (_records(["a"]), 1),
            ([], 0),
            (_records(["b"]), 1),
            ([], 0),
        ]
        pipeline = AsyncETLPipeline(**parts, sleep=mocker.AsyncMock())
        await pipeline.run(query="q", page_size=1, total_limit=5)
        first = pipeline.last_run_metrics
        first.processed = 99
        await pipeline.run(query="q", page_size=1, total_limit=5)
        assert pipeline.last_run_metrics.processed == 1

    def test_the_sync_facade_exposes_the_last_run_metrics(self, mocker):
        parts = _parts(mocker, [_records(["a"])])
        pipeline = ETLPipeline(**parts, sleep=mocker.AsyncMock())
        assert pipeline.last_run_metrics is None
        pipeline.run(query="q", page_size=1, total_limit=1)
        assert pipeline.last_run_metrics.processed == 1


class TestMetricsModel:
    def test_snapshot_copies_the_token_usage(self):
        metrics = RunMetrics(token_usage=TokenUsage(requests=1))
        copy = metrics.snapshot()
        copy.token_usage.requests = 5
        assert metrics.token_usage.requests == 1

    def test_token_usage_adds_and_subtracts(self):
        total = TokenUsage(2, 10, 3) + TokenUsage(1, 5, 1)
        assert total == TokenUsage(3, 15, 4)
        assert total - TokenUsage(1, 5, 1) == TokenUsage(2, 10, 3)
