from __future__ import annotations

import warnings

import httpx
import pytest
from pydantic import ConfigDict

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


class TestStrictSections:
    def test_a_mistyped_key_in_a_nested_section_is_rejected_and_named(self, tmp_path):
        with pytest.raises(ConfigurationError, match=r"search\.bm25\.titel: Extra inputs are not permitted"):
            validate_config(BaseAppConfig, {"search": {"bm25": {"titel": 3.0}}}, tmp_path / "c.yaml")

    @pytest.mark.parametrize("old", ["max_records", "max_workers"])
    def test_the_keys_renamed_in_0_4_are_rejected(self, old, tmp_path):
        with pytest.raises(ConfigurationError, match=f"pipeline.{old}: Extra inputs are not permitted"):
            validate_config(BaseAppConfig, {"pipeline": {old: 7}}, tmp_path / "c.yaml")

    def test_unknown_top_level_keys_are_kept_for_the_application(self):
        config = BaseAppConfig.model_validate({"catalogue": {"anything": 1}})
        assert config.model_extra == {"catalogue": {"anything": 1}}

    def test_a_subclass_that_opts_out_drops_unknown_section_keys_with_a_warning(self):
        class LenientConfig(BaseAppConfig):
            strict_sections = False

        raw = {
            "pipeline": {"total_limit": 5, "max_records": 9},
            "search": {"bm25": {"title": 2.0, "titel": 3.0}},
            "extra_section": {"kept": True},
        }
        with pytest.warns(UserWarning, match="Ignoring unknown config key") as warned:
            config = LenientConfig.model_validate(raw)
        assert sorted(str(warning.message) for warning in warned) == [
            "Ignoring unknown config key pipeline.max_records",
            "Ignoring unknown config key search.bm25.titel",
        ]
        assert (config.pipeline.total_limit, config.search.bm25.title) == (5, 2.0)
        assert config.model_extra == {"extra_section": {"kept": True}}

    def test_the_opt_out_leaves_a_section_that_is_not_a_mapping_to_validation(self):
        class LenientConfig(BaseAppConfig):
            strict_sections = False

        with pytest.raises(ValueError, match="valid dictionary or instance of GraphConfig"):
            LenientConfig.model_validate({"search": {"graph": "odd"}})

    def test_the_opt_out_leaves_a_section_that_declares_its_own_extra_alone(self):
        class OpenPipeline(PipelineConfig):
            model_config = ConfigDict(extra="allow")

        class LenientConfig(BaseAppConfig):
            strict_sections = False
            pipeline: OpenPipeline = OpenPipeline()

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            config = LenientConfig.model_validate({"pipeline": {"total_limit": 2, "custom": "x"}})
        assert config.pipeline.model_extra == {"custom": "x"}

    def test_a_strict_config_validates_a_non_mapping_as_before(self):
        with pytest.raises(ValueError, match="valid dictionary or instance"):
            BaseAppConfig.model_validate(["pipeline"])

    def test_the_opt_out_passes_a_non_mapping_to_validation(self):
        class LenientConfig(BaseAppConfig):
            strict_sections = False

        with pytest.raises(ValueError, match="valid dictionary or instance"):
            LenientConfig.model_validate(["pipeline"])

    def test_a_section_that_is_not_a_mapping_is_still_rejected(self):
        with pytest.raises(ValueError, match="valid dictionary or instance"):
            PipelineConfig.model_validate(["total_limit", 1])


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
        collaborators["state_manager"].failure_counts.return_value = {}
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
    async def test_the_max_records_run_alias_is_gone(self, mocker):
        pipeline = AsyncETLPipeline(
            mocker.AsyncMock(),
            mocker.AsyncMock(),
            mocker.AsyncMock(),
            mocker.AsyncMock(),
            mocker.AsyncMock(),
        )
        with pytest.raises(TypeError, match="max_records"):
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
        fetcher = extractor._fetcher
        assert (fetcher._max_retries, fetcher._backoff_factor, extractor._sleep_before_search) == (5, 1.5, 0.5)

    @pytest.mark.parametrize(
        ("section", "limiter_type"),
        [
            (RateLimitConfig(max_concurrency=2), SemaphoreRateLimiter),
            (RateLimitConfig(max_rate=1, time_period=3.0), AioLimiterRateLimiter),
        ],
    )
    def test_arxiv_extractor_takes_its_rate_limiter_from_the_full_text_section(self, mocker, section, limiter_type):
        extractor = AsyncArxivExtractor.from_config(
            HttpConfig(),
            client=mocker.Mock(),
            pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=mocker.Mock(spec=LatexTarballParser),
            full_text=section,
        )
        assert isinstance(extractor._fetcher._rate_limiter, limiter_type)

    def test_arxiv_extractor_without_a_full_text_section_has_no_rate_limiter(self, mocker):
        extractor = AsyncArxivExtractor.from_config(
            HttpConfig(),
            client=mocker.Mock(),
            pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=mocker.Mock(spec=LatexTarballParser),
        )
        assert extractor._fetcher._rate_limiter is None

    def test_arxiv_extractor_options_override_the_config(self, mocker):
        limiter = SemaphoreRateLimiter()
        extractor = AsyncArxivExtractor.from_config(
            HttpConfig(max_retries=5),
            client=mocker.Mock(),
            pdf_parser=mocker.Mock(spec=PdfPlumberParser),
            latex_parser=mocker.Mock(spec=LatexTarballParser),
            max_retries=1,
            rate_limiter=limiter,
            full_text=RateLimitConfig(max_concurrency=9),
        )
        assert extractor._fetcher._max_retries == 1
        assert extractor._sleep_before_search == 3.0
        assert extractor._fetcher._rate_limiter is limiter

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
