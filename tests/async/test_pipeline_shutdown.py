from __future__ import annotations

import asyncio
import signal
import threading

import pytest

from sci_etl_core.exceptions import PipelineAborted, PipelineInterrupted, UpstreamError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.signals import ShutdownSignal
from sci_etl_core.state.async_base import AsyncStateManager

TEST_SIGNAL = signal.SIGTERM


@pytest.fixture(autouse=True)
def restore_process_handler():
    saved = signal.getsignal(TEST_SIGNAL)
    yield
    signal.signal(TEST_SIGNAL, saved)


def _records(n: int, start: int = 0) -> list[RawRecord]:
    return [RawRecord(record_id=str(i), title=f"t{i}", abstract=f"a{i}") for i in range(start, start + n)]


def _collaborators(mocker, pages):
    extractor = mocker.Mock(spec=AsyncExtractor)
    extractor.search = mocker.AsyncMock(return_value=b"<feed/>")
    extractor.parse_listing = mocker.Mock(side_effect=[(page, len(page)) for page in pages] + [([], 0)] * 5)
    extractor.fetch_full_text = mocker.AsyncMock(side_effect=lambda record: f"text-{record.record_id}")
    relevance = mocker.Mock(spec=AsyncRelevanceFilter)
    relevance.is_relevant = mocker.AsyncMock(return_value=True)
    entity = mocker.Mock(spec=AsyncEntityExtractor)
    entity.extract = mocker.AsyncMock(return_value=[{"name": "X"}])
    exporter = mocker.Mock(spec=AsyncExporter)
    exporter.export = mocker.AsyncMock()
    state = mocker.Mock(spec=AsyncStateManager)
    state.load_processed_ids = mocker.AsyncMock(return_value=set())
    state.load_metadata = mocker.AsyncMock(return_value=PipelineMetadata(last_start_index=40))
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


def _pipeline(mocker, pages, **kwargs):
    parts = _collaborators(mocker, pages)
    kwargs.setdefault("sleep", mocker.AsyncMock())
    return AsyncETLPipeline(**parts, **kwargs), parts


def _marked(state) -> list[str]:
    return [call.args[0] for call in state.mark_processed.await_args_list]


class TestShutdownDuringAPage:
    @pytest.mark.asyncio
    async def test_in_flight_records_finish_and_the_rest_wait_for_the_next_run(self, mocker):
        shutdown = ShutdownSignal(signals=())
        pipeline, parts = _pipeline(mocker, [_records(5)], max_concurrency=2, shutdown=shutdown)
        started: list[str] = []

        async def fetch(record):
            started.append(record.record_id)
            if len(started) == 2:
                shutdown.request()
            await asyncio.sleep(0.01)
            return "text"

        parts["extractor"].fetch_full_text.side_effect = fetch
        with pytest.raises(PipelineInterrupted) as raised:
            await pipeline.run(query="q", page_size=5, total_limit=5)
        assert started == ["0", "1"]
        assert _marked(parts["state_manager"]) == ["0", "1"]
        assert raised.value.partial_count == 2
        assert isinstance(raised.value, PipelineAborted)

    @pytest.mark.asyncio
    async def test_the_saved_offset_stays_at_the_interrupted_page(self, mocker):
        shutdown = ShutdownSignal(signals=())
        pipeline, parts = _pipeline(mocker, [_records(2), _records(2, 2)], max_concurrency=1, shutdown=shutdown)
        calls = 0

        async def fetch(record):
            nonlocal calls
            calls += 1
            if calls == 3:
                shutdown.request()
            return "text"

        parts["extractor"].fetch_full_text.side_effect = fetch
        with pytest.raises(PipelineInterrupted):
            await pipeline.run(query="q", page_size=2, total_limit=10)
        saved = [call.args[0].last_start_index for call in parts["state_manager"].save_metadata.await_args_list]
        assert saved == [42, 42]
        parts["state_manager"].flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_run_that_reaches_its_limit_on_the_interrupted_page_ends_normally(self, mocker):
        shutdown = ShutdownSignal(signals=())
        pipeline, parts = _pipeline(mocker, [_records(2)], max_concurrency=2, shutdown=shutdown)

        async def fetch(record):
            if record.record_id == "1":
                shutdown.request()
            return "text"

        parts["extractor"].fetch_full_text.side_effect = fetch
        assert await pipeline.run(query="q", page_size=2, total_limit=2) == 2


class TestShutdownBetweenRequests:
    @pytest.mark.asyncio
    async def test_a_request_made_before_the_run_fetches_nothing(self, mocker):
        shutdown = ShutdownSignal(signals=())
        shutdown.request()
        pipeline, parts = _pipeline(mocker, [_records(1)], shutdown=shutdown)
        with pytest.raises(PipelineInterrupted) as raised:
            await pipeline.run(query="q", page_size=1, total_limit=1)
        assert raised.value.partial_count == 0
        parts["extractor"].search.assert_not_awaited()
        parts["state_manager"].flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_pending_listing_fetch_is_cancelled(self, mocker):
        shutdown = ShutdownSignal(signals=())
        pipeline, parts = _pipeline(mocker, [_records(1)], shutdown=shutdown)
        cancelled = asyncio.Event()

        async def slow_search(*_args):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        parts["extractor"].search.side_effect = slow_search
        run = asyncio.create_task(pipeline.run(query="q", page_size=1, total_limit=1))
        await asyncio.sleep(0.01)
        shutdown.request()
        with pytest.raises(PipelineInterrupted):
            await asyncio.wait_for(run, timeout=2)
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_the_wait_between_pages_is_cut_short(self, mocker):
        shutdown = ShutdownSignal(signals=())
        pipeline, parts = _pipeline(mocker, [_records(1), _records(1, 1)], shutdown=shutdown, sleep=asyncio.sleep)
        saved = asyncio.Event()
        parts["state_manager"].save_metadata.side_effect = lambda metadata: saved.set()
        run = asyncio.create_task(pipeline.run(query="q", page_size=1, total_limit=5, sleep_between=30))
        await asyncio.wait_for(saved.wait(), timeout=2)
        shutdown.request()
        with pytest.raises(PipelineInterrupted) as raised:
            await asyncio.wait_for(run, timeout=2)
        assert raised.value.partial_count == 1
        assert parts["extractor"].search.await_count == 1

    @pytest.mark.asyncio
    async def test_a_listing_failure_is_still_an_abort_when_a_shutdown_is_configured(self, mocker):
        pipeline, parts = _pipeline(mocker, [_records(1)], shutdown=ShutdownSignal(signals=()))
        parts["extractor"].search.side_effect = UpstreamError("down")
        with pytest.raises(PipelineAborted) as raised:
            await pipeline.run(query="q", page_size=1, total_limit=1)
        assert not isinstance(raised.value, PipelineInterrupted)

    @pytest.mark.asyncio
    async def test_cancelling_the_run_cancels_a_raced_fetch(self, mocker):
        pipeline, parts = _pipeline(mocker, [_records(1)], shutdown=ShutdownSignal(signals=()))
        cancelled = asyncio.Event()

        async def slow_search(*_args):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        parts["extractor"].search.side_effect = slow_search
        run = asyncio.create_task(pipeline.run(query="q", page_size=1, total_limit=1))
        await asyncio.sleep(0.01)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert cancelled.is_set()
        parts["state_manager"].flush.assert_awaited_once()


class TestFlushOnEveryExit:
    @pytest.mark.asyncio
    async def test_a_completed_run_flushes_state(self, mocker):
        pipeline, parts = _pipeline(mocker, [_records(1)])
        assert await pipeline.run(query="q", page_size=1, total_limit=1) == 1
        parts["state_manager"].flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_an_aborted_run_flushes_state_before_raising(self, mocker):
        pipeline, parts = _pipeline(mocker, [_records(1)])
        parts["extractor"].search.side_effect = UpstreamError("down")
        with pytest.raises(PipelineAborted):
            await pipeline.run(query="q", page_size=1, total_limit=1)
        parts["state_manager"].flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_flush_failure_after_an_abort_is_logged_and_the_abort_raised(self, mocker):
        lines: list[str] = []
        pipeline, parts = _pipeline(mocker, [_records(1)], logger=lines.append)
        parts["extractor"].search.side_effect = UpstreamError("down")
        parts["state_manager"].flush.side_effect = OSError("disk gone")
        with pytest.raises(PipelineAborted):
            await pipeline.run(query="q", page_size=1, total_limit=1)
        assert lines[-1] == "State flush failed: OSError('disk gone')"

    @pytest.mark.asyncio
    async def test_a_flush_failure_after_a_completed_run_is_raised(self, mocker):
        pipeline, parts = _pipeline(mocker, [_records(1)])
        parts["state_manager"].flush.side_effect = OSError("disk gone")
        with pytest.raises(OSError, match="disk gone"):
            await pipeline.run(query="q", page_size=1, total_limit=1)


class TestSignalHandlers:
    @pytest.mark.asyncio
    async def test_a_real_signal_stops_the_run_and_handlers_are_restored(self, mocker):
        original = signal.getsignal(TEST_SIGNAL)
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        pipeline, parts = _pipeline(mocker, [_records(3)], max_concurrency=1, shutdown=shutdown)

        async def fetch(record):
            assert signal.getsignal(TEST_SIGNAL) is not original
            signal.raise_signal(TEST_SIGNAL)
            await asyncio.sleep(0.01)
            return "text"

        parts["extractor"].fetch_full_text.side_effect = fetch
        with pytest.raises(PipelineInterrupted) as raised:
            await pipeline.run(query="q", page_size=3, total_limit=3)
        assert raised.value.partial_count == 1
        assert signal.getsignal(TEST_SIGNAL) is original

    @pytest.mark.asyncio
    async def test_an_enclosing_guard_keeps_its_handlers_after_the_run(self, mocker):
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        pipeline, _ = _pipeline(mocker, [_records(1)], shutdown=shutdown)
        with shutdown.guard():
            installed = signal.getsignal(TEST_SIGNAL)
            await pipeline.run(query="q", page_size=1, total_limit=1)
            assert signal.getsignal(TEST_SIGNAL) is installed

    def test_the_pipeline_exposes_its_shutdown_signal(self, mocker):
        shutdown = ShutdownSignal(signals=())
        pipeline, _ = _pipeline(mocker, [], shutdown=shutdown)
        assert pipeline.shutdown is shutdown


class TestSyncFacadeShutdown:
    def _facade(self, mocker, pages, **kwargs):
        parts = _collaborators(mocker, pages)
        return ETLPipeline(**parts, sleep=mocker.AsyncMock(), **kwargs), parts

    def test_a_signal_raised_while_the_background_loop_works_stops_the_run(self, mocker):
        original = signal.getsignal(TEST_SIGNAL)
        shutdown = ShutdownSignal(signals=(TEST_SIGNAL,))
        facade, parts = self._facade(mocker, [_records(3)], max_concurrency=1, shutdown=shutdown)
        threads: list[str] = []

        async def fetch(record):
            threads.append(threading.current_thread().name)
            signal.raise_signal(TEST_SIGNAL)
            for _ in range(200):
                if shutdown.triggered:
                    break
                await asyncio.sleep(0.01)
            return "text"

        parts["extractor"].fetch_full_text.side_effect = fetch
        with pytest.raises(PipelineInterrupted) as raised:
            facade.run(query="q", page_size=3, total_limit=3)
        assert raised.value.partial_count == 1
        assert threads == ["sci-etl-sync-bridge"]
        assert signal.getsignal(TEST_SIGNAL) is original

    def test_without_a_shutdown_signal_no_handler_is_installed(self, mocker):
        original = signal.getsignal(TEST_SIGNAL)
        facade, parts = self._facade(mocker, [_records(1)])

        async def fetch(record):
            assert signal.getsignal(TEST_SIGNAL) is original
            return "text"

        parts["extractor"].fetch_full_text.side_effect = fetch
        assert facade.run(query="q", page_size=1, total_limit=1) == 1
