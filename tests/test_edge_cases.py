from __future__ import annotations

import pandas as pd
import pytest

from sci_etl_core.exceptions import LLMError
from sci_etl_core.exporters.base import Exporter
from sci_etl_core.exporters.csv_exporter import CsvUpsertExporter
from sci_etl_core.extractors.base import Extractor
from sci_etl_core.llm.extraction import EntityExtractor
from sci_etl_core.llm.openai_compatible import OpenAICompatibleClient
from sci_etl_core.llm.relevance import RelevanceFilter
from sci_etl_core.models import PipelineMetadata, RawRecord
from sci_etl_core.pipeline import ETLPipeline
from sci_etl_core.processors.dedup import DeduplicationStep, NeighborMatcher
from sci_etl_core.processors.normalization import DefaultKeyNormalizer
from sci_etl_core.state.base import StateManager
from sci_etl_core.state.file_state import FileStateManager


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    mocker.patch("sci_etl_core.pipeline.time.sleep")


def _pipeline(mocker, records, *, max_workers=4):
    extractor = mocker.Mock(spec=Extractor)
    extractor.search.return_value = b"<feed/>"
    extractor.parse_listing.side_effect = [(records, len(records))] + [([], 0)] * 5
    extractor.fetch_full_text.side_effect = lambda r: f"text-{r.record_id}"
    relevance = mocker.Mock(spec=RelevanceFilter)
    relevance.is_relevant.return_value = True
    entity = mocker.Mock(spec=EntityExtractor)
    entity.extract.return_value = [{"name": "X"}]
    exporter = mocker.Mock(spec=Exporter)
    state = mocker.Mock(spec=StateManager)
    state.load_processed_ids.return_value = set()
    state.load_metadata.return_value = PipelineMetadata(last_start_index=0)
    pipeline = ETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entity,
        exporter=exporter,
        state_manager=state,
        destination="out.csv",
        max_workers=max_workers,
    )
    return pipeline, state


class TestPipelineEmptyRecordId:
    def test_record_without_id_is_processed_but_not_marked(self, mocker):
        pipeline, state = _pipeline(mocker, [RawRecord(record_id="", title="t", abstract="a")])
        assert pipeline.run(query="q", max_records=1, sleep_between=0) == 1
        state.mark_processed.assert_not_called()


def _message(mocker, content):
    choice = mocker.Mock()
    choice.message.content = content
    response = mocker.Mock()
    response.choices = [choice]
    return response


class TestOpenAIRetryPaths:
    @pytest.fixture
    def patched_openai(self, mocker):
        return mocker.patch("sci_etl_core.llm.openai_compatible.OpenAI").return_value

    def test_retryable_error_exhausts_and_raises(self, patched_openai, mocker):
        from openai import RateLimitError

        class FakeRateLimit(RateLimitError):
            def __init__(self):
                Exception.__init__(self, "rate limited")

        patched_openai.chat.completions.create.side_effect = FakeRateLimit()
        sleep = mocker.patch("sci_etl_core.llm.openai_compatible.time.sleep")
        client = OpenAICompatibleClient(api_key="k", base_url="u", model="m", max_retries=3)
        with pytest.raises(LLMError, match="after 3 attempts"):
            client.complete_json("s", "u")
        assert patched_openai.chat.completions.create.call_count == 3
        assert sleep.call_count == 2

    def test_retryable_error_then_success(self, patched_openai, mocker):
        from openai import APITimeoutError

        class FakeTimeout(APITimeoutError):
            def __init__(self):
                Exception.__init__(self, "timeout")

        patched_openai.chat.completions.create.side_effect = [FakeTimeout(), _message(mocker, '{"ok": 1}')]
        mocker.patch("sci_etl_core.llm.openai_compatible.time.sleep")
        client = OpenAICompatibleClient(api_key="k", base_url="u", model="m", max_retries=3)
        assert client.complete_json("s", "u") == {"ok": 1}

    def test_empty_choices_raises(self, patched_openai, mocker):
        response = mocker.Mock()
        response.choices = []
        patched_openai.chat.completions.create.return_value = response
        client = OpenAICompatibleClient(api_key="k", base_url="u", model="m")
        with pytest.raises(LLMError, match="no choices"):
            client.complete_json("s", "u")


class TestDedupRepeatDrop:
    def test_already_dropped_index_is_skipped(self):
        class RepeatDrop(NeighborMatcher):
            def find_matches(self, frame, threshold):
                return [(0, 2), (1, 2)]

        frame = pd.DataFrame({"_norm_key": ["a", "b", "c"], "value": [None, None, 7.0]})
        result = DeduplicationStep("_norm_key", matcher=RepeatDrop()).process(frame)
        assert len(result) == 2
        assert 7.0 in result["value"].to_numpy()


class TestCsvMissingColumn:
    def test_missing_value_column_is_added(self, tmp_path):
        exporter = CsvUpsertExporter(
            key_column="name", value_columns=["ra", "dec"], normalizer=DefaultKeyNormalizer()
        )
        dest = tmp_path / "out.csv"
        pd.DataFrame({"name": ["Alpha"], "ra": [1.0]}).to_csv(dest, index=False)
        exporter.export([{"name": "Beta", "ra": 2.0, "dec": 3.0}], str(dest))
        assert "dec" in pd.read_csv(dest).columns


class TestStateOsError:
    def test_load_processed_ids_returns_empty_on_os_error(self, tmp_path, mocker):
        manager = FileStateManager(tmp_path / "ids.txt", tmp_path / "meta.json")
        manager._processed_ids_file.write_text("2401.1\n", encoding="utf-8")
        mocker.patch("pathlib.Path.open", side_effect=OSError("io"))
        assert manager.load_processed_ids() == set()
