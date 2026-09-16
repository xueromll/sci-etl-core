from __future__ import annotations

import warnings

import httpx
import pytest

from sci_etl_core import AsyncArxivExtractor, AsyncETLPipeline, AsyncOpenAICompatibleClient, ETLPipeline
from sci_etl_core.config import (
    BaseAppConfig,
    HttpConfig,
    LLMConfig,
    PipelineConfig,
    RateLimitConfig,
    SearchConfig,
    validate_config,
)
from sci_etl_core.exceptions import ConfigurationError
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser
from sci_etl_core.rate_limiter import AioLimiterRateLimiter, SemaphoreRateLimiter
from sci_etl_core.search.fusion import FusionParams
from sci_etl_core.search.graph import GraphParams
from sci_etl_core.search.hybrid_async import HybridParams
from sci_etl_core.search.store_base import BM25Weights


class TestRenamedPipelineKeys:
    @pytest.mark.parametrize(("old", "new"), [("max_records", "total_limit"), ("max_workers", "max_concurrency")])
    def test_an_old_key_is_read_as_the_new_one_with_a_warning(self, old, new):
        with pytest.warns(DeprecationWarning, match=f"pipeline.{old} is deprecated.*use pipeline.{new}"):
            config = PipelineConfig.model_validate({old: 7})
        assert getattr(config, new) == 7

    def test_both_names_with_the_same_value_are_accepted(self):
        with pytest.warns(DeprecationWarning):
            config = PipelineConfig.model_validate({"max_records": 9, "total_limit": 9})
        assert config.total_limit == 9

    def test_both_names_with_different_values_are_a_configuration_error(self, tmp_path):
        with pytest.warns(DeprecationWarning), pytest.raises(ConfigurationError, match="set only total_limit"):
            validate_config(BaseAppConfig, {"pipeline": {"max_records": 1, "total_limit": 2}}, tmp_path / "c.yaml")

    def test_an_old_key_is_still_validated(self):
        with pytest.warns(DeprecationWarning), pytest.raises(ValueError, match="greater than or equal to 1"):
            PipelineConfig.model_validate({"max_workers": 0})

    def test_a_subclass_that_forbids_extra_keys_still_accepts_an_old_key(self):
        class StrictPipeline(PipelineConfig):
            model_config = {"extra": "forbid"}

        with pytest.warns(DeprecationWarning):
            assert StrictPipeline.model_validate({"max_records": 3}).total_limit == 3

    def test_a_section_that_is_not_a_mapping_is_still_rejected(self):
        with pytest.raises(ValueError, match="valid dictionary or instance"):
            PipelineConfig.model_validate(["max_records", 1])

    def test_new_keys_raise_no_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            PipelineConfig.model_validate({"total_limit": 1, "max_concurrency": 2})
            PipelineConfig.model_validate(PipelineConfig())

    @pytest.mark.parametrize(("old", "new"), [("max_records", "total_limit"), ("max_workers", "max_concurrency")])
    def test_the_old_attribute_reads_the_new_field_with_a_warning(self, old, new):
        config = PipelineConfig(total_limit=4, max_concurrency=5)
        with pytest.warns(DeprecationWarning, match=f"{old} is deprecated; use {new}"):
            assert getattr(config, old) == getattr(config, new)


class TestPipelineConfigRunArguments:
    def test_run_arguments_mirror_the_run_signature(self):
        config = PipelineConfig(
            search_query="all:galaxy", page_size=25, total_limit=80, sleep_between=1.5, newest_first=True
        )
        assert config.run_arguments() == {
            "query": "all:galaxy",
            "page_size": 25,
            "total_limit": 80,
            "sleep_between": 1.5,
            "newest_first": True,
        }

    @pytest.mark.asyncio
    async def test_the_async_pipeline_takes_its_concurrency_and_run_from_the_config(self, mocker):
        config = PipelineConfig(search_query="q", max_concurrency=3, page_size=5, total_limit=0)
        collaborators = {
            name: mocker.AsyncMock()
            for name in ("extractor", "relevance_filter", "entity_extractor", "exporter", "state_manager")
        }
        pipeline = AsyncETLPipeline.from_config(config, destination="out.csv", **collaborators)
        assert pipeline._semaphore._value == 3
        assert await pipeline.run(**config.run_arguments()) == 0

    def test_an_explicit_argument_overrides_the_config(self, mocker):
        config = PipelineConfig(max_concurrency=3)
        pipeline = AsyncETLPipeline.from_config(
            config,
            extractor=mocker.Mock(),
            relevance_filter=mocker.Mock(),
            entity_extractor=mocker.Mock(),
            exporter=mocker.Mock(),
            state_manager=mocker.Mock(),
            destination="out.csv",
            max_concurrency=1,
        )
        assert pipeline._semaphore._value == 1

    def test_the_sync_pipeline_takes_its_concurrency_from_the_config(self, mocker):
        pipeline = ETLPipeline.from_config(
            PipelineConfig(max_concurrency=2),
            extractor=mocker.Mock(),
            relevance_filter=mocker.Mock(),
            entity_extractor=mocker.Mock(),
            exporter=mocker.Mock(),
            state_manager=mocker.Mock(),
            destination="out.csv",
            run_timeout=10,
        )
        assert pipeline._async._semaphore._value == 2
        assert pipeline._run_timeout == 10

    @pytest.mark.asyncio
    async def test_the_max_records_run_alias_warns(self, mocker):
        pipeline = AsyncETLPipeline(
            extractor=mocker.AsyncMock(),
            relevance_filter=mocker.AsyncMock(),
            entity_extractor=mocker.AsyncMock(),
            exporter=mocker.AsyncMock(),
            state_manager=mocker.AsyncMock(),
            destination="out.csv",
        )
        with pytest.warns(DeprecationWarning, match="run\\(max_records=\\) is deprecated"):
            with pytest.raises(ValueError):
                await pipeline.run(query="q", max_records=0)


class TestComponentsFromConfig:
    @pytest.mark.asyncio
    async def test_http_config_builds_a_client_with_its_timeout_and_user_agent(self):
        client = HttpConfig(timeout=7, user_agent="me/1.0").build_client()
        try:
            assert isinstance(client, httpx.AsyncClient)
            assert client.timeout.connect == 7
            assert client.headers["User-Agent"] == "me/1.0"
        finally:
            await client.aclose()

    def test_rate_limit_config_builds_a_semaphore_without_a_rate(self):
        limiter = RateLimitConfig(max_concurrency=2).build_limiter()
        assert isinstance(limiter, SemaphoreRateLimiter)

    def test_rate_limit_config_builds_a_token_bucket_with_a_rate(self):
        limiter = RateLimitConfig(max_rate=2, time_period=3).build_limiter()
        assert isinstance(limiter, AioLimiterRateLimiter)

    def test_arxiv_extractor_takes_retries_and_search_delay_from_the_config(self, mocker):
        extractor = AsyncArxivExtractor.from_config(
            HttpConfig(max_retries=5, backoff_factor=1.5),
            PipelineConfig(search_delay=0.5),
            client=mocker.Mock(),
            pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=mocker.Mock(spec=LatexTarballParser),
        )
        assert (extractor._max_retries, extractor._backoff_factor, extractor._sleep_before_search) == (5, 1.5, 0.5)

    def test_arxiv_extractor_options_override_the_config(self, mocker):
        limiter = SemaphoreRateLimiter()
        extractor = AsyncArxivExtractor.from_config(
            HttpConfig(max_retries=5),
            client=mocker.Mock(),
            pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=mocker.Mock(spec=LatexTarballParser),
            max_retries=1,
            rate_limiter=limiter,
        )
        assert extractor._max_retries == 1
        assert extractor._sleep_before_search == 3.0
        assert extractor._rate_limiter is limiter

    def test_chat_client_takes_its_connection_settings_from_the_config(self, mocker):
        openai = mocker.patch("sci_etl_core.llm.openai_compatible_async.AsyncOpenAI")
        llm = LLMConfig(api_key="sk-config", base_url="https://api.example.com/v1", model="m-1", timeout=33)
        client = AsyncOpenAICompatibleClient.from_config(llm, temperature=0.5)
        openai.assert_called_once_with(api_key="sk-config", base_url="https://api.example.com/v1", max_retries=0)
        assert (client._model, client._default_timeout, client._temperature) == ("m-1", 33, 0.5)


class TestSearchConfig:
    def test_defaults_match_the_parameter_dataclasses(self):
        search = SearchConfig()
        assert search.bm25.to_weights() == BM25Weights()
        assert search.fusion.to_params() == FusionParams()
        assert search.hybrid.to_params() == HybridParams()
        assert search.graph.to_params() == GraphParams()

    def test_values_from_yaml_reach_the_dataclasses(self, tmp_path):
        raw = {
            "search": {
                "bm25": {"title": 2, "abstract": 1, "body": 0.5},
                "fusion": {"k": 10, "weights": [1, 2]},
                "hybrid": {"candidate_pool": 30, "chunk_pool_factor": 8},
                "graph": {
                    "depth": 1,
                    "fanout": 4,
                    "min_weight": 0.5,
                    "max_nodes": 50,
                    "mutual_only": False,
                    "max_iterations": 5,
                },
            }
        }
        search = validate_config(BaseAppConfig, raw, tmp_path / "c.yaml").search
        assert search.bm25.to_weights() == BM25Weights(title=2, abstract=1, body=0.5)
        assert search.fusion.to_params() == FusionParams(k=10, weights=(1.0, 2.0))
        assert search.hybrid.to_params() == HybridParams(candidate_pool=30, chunk_pool_factor=8)
        assert search.graph.to_params() == GraphParams(
            depth=1, fanout=4, min_weight=0.5, max_nodes=50, mutual_only=False, max_iterations=5
        )

    @pytest.mark.parametrize(
        "raw",
        [
            {"bm25": {"title": -1}},
            {"bm25": {"body": "inf"}},
            {"fusion": {"k": 0}},
            {"hybrid": {"candidate_pool": 0}},
            {"graph": {"depth": -1}},
            {"graph": {"min_weight": "nan"}},
        ],
    )
    def test_invalid_values_are_configuration_errors(self, raw, tmp_path):
        with pytest.raises(ConfigurationError, match="Invalid configuration"):
            validate_config(BaseAppConfig, {"search": raw}, tmp_path / "c.yaml")

    def test_a_negative_fusion_weight_is_rejected_when_building_the_params(self):
        config = SearchConfig.model_validate({"fusion": {"weights": [-1]}})
        with pytest.raises(ValueError, match="must be finite and not negative"):
            config.fusion.to_params()
