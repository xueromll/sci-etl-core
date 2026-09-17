from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from sci_etl_core.exceptions import ConfigurationError

if TYPE_CHECKING:
    import httpx

    from sci_etl_core.rate_limiter import AsyncRateLimiter
    from sci_etl_core.search.fusion import FusionParams
    from sci_etl_core.search.graph import GraphParams
    from sci_etl_core.search.hybrid_async import HybridParams
    from sci_etl_core.search.store_base import BM25Weights

T = TypeVar("T", bound="BaseAppConfig")

_RENAMED_PIPELINE_KEYS: dict[str, str] = {"max_records": "total_limit", "max_workers": "max_concurrency"}


class LLMConfig(BaseModel):
    """Chat-completion endpoint settings.

    :meth:`~sci_etl_core.llm.openai_compatible_async.AsyncOpenAICompatibleClient.from_config`
    builds a client from them. ``api_key`` is a :class:`~pydantic.SecretStr`, so it never appears in a
    ``repr`` or a log line. :func:`load_config` takes it from the environment
    variable it names, and falls back to the YAML value when that is unset.
    ``timeout`` is in seconds.
    """

    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: int = Field(default=120, gt=0)


class HttpConfig(BaseModel):
    """HTTP settings for the clients and extractors that call a remote source."""

    user_agent: str = "sci-etl-core/0.1"
    max_retries: int = Field(default=3, ge=1)
    backoff_factor: float = Field(default=2.0, ge=0)
    timeout: int = Field(default=25, gt=0)

    def build_client(self) -> httpx.AsyncClient:
        """Build an ``httpx.AsyncClient`` with this ``timeout`` and ``user_agent``.

        ``max_retries`` and ``backoff_factor`` are applied by the extractor, as
        :meth:`~sci_etl_core.extractors.arxiv_async.AsyncArxivExtractor.from_config`
        does, not by the client. Needs the ``async`` extra.
        """
        from sci_etl_core.http_async import build_async_client

        return build_async_client(timeout=self.timeout, user_agent=self.user_agent)


class RateLimitConfig(BaseModel):
    """A concurrency cap, or a token bucket when ``max_rate`` is set."""

    max_concurrency: int = Field(default=4, ge=1)
    max_rate: float | None = Field(default=None, gt=0)
    time_period: float = Field(default=1.0, gt=0)

    def build_limiter(self) -> AsyncRateLimiter:
        """Build the limiter these settings describe, as :func:`~sci_etl_core.rate_limiter.build_rate_limiter` does."""
        from sci_etl_core.rate_limiter import build_rate_limiter

        return build_rate_limiter(
            max_concurrency=self.max_concurrency, max_rate=self.max_rate, time_period=self.time_period
        )


class PipelineConfig(BaseModel):
    """Settings for :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` and its runs.

    ``max_concurrency`` configures the pipeline (see ``from_config``), and
    :meth:`run_arguments` returns the arguments for ``run()``.
    ``search_delay`` is the arXiv extractor's pause before each listing
    request.

    .. deprecated:: 0.4.0
        The keys ``max_records`` and ``max_workers`` are read as
        ``total_limit`` and ``max_concurrency``, with a
        :class:`DeprecationWarning`. They will stop being accepted in 0.5.0.
    """

    search_query: str = ""
    total_limit: int = Field(default=100, ge=0)
    page_size: int = Field(default=100, ge=1)
    search_delay: float = Field(default=3.0, ge=0)
    sleep_between: float = Field(default=5.0, ge=0)
    max_concurrency: int = Field(default=6, ge=1)
    newest_first: bool = False

    @model_validator(mode="before")
    @classmethod
    def _read_renamed_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        renamed = dict(data)
        for old, new in _RENAMED_PIPELINE_KEYS.items():
            if old not in renamed:
                continue
            warnings.warn(
                f"pipeline.{old} is deprecated and will be removed in sci-etl-core 0.5.0; use pipeline.{new}",
                DeprecationWarning,
                stacklevel=2,
            )
            value = renamed.pop(old)
            if new in renamed and renamed[new] != value:
                raise ValueError(f"{old} and {new} are the same setting; set only {new}")
            renamed[new] = value
        return renamed

    @property
    def max_records(self) -> int:
        """Deprecated alias of :attr:`total_limit`."""
        warnings.warn(
            "PipelineConfig.max_records is deprecated; use total_limit", DeprecationWarning, stacklevel=2
        )
        return self.total_limit

    @property
    def max_workers(self) -> int:
        """Deprecated alias of :attr:`max_concurrency`."""
        warnings.warn(
            "PipelineConfig.max_workers is deprecated; use max_concurrency", DeprecationWarning, stacklevel=2
        )
        return self.max_concurrency

    def run_arguments(self) -> dict[str, Any]:
        """Return the keyword arguments for ``run()`` these settings describe.

        Unpack them into the call, adding ``start_index`` when needed:
        ``await pipeline.run(**config.pipeline.run_arguments())``.
        """
        return {
            "query": self.search_query,
            "page_size": self.page_size,
            "total_limit": self.total_limit,
            "sleep_between": self.sleep_between,
            "newest_first": self.newest_first,
        }


class BM25WeightsConfig(BaseModel):
    """Per-field BM25 weights, as :class:`~sci_etl_core.search.store_base.BM25Weights`."""

    title: float = Field(default=10.0, ge=0, allow_inf_nan=False)
    abstract: float = Field(default=4.0, ge=0, allow_inf_nan=False)
    body: float = Field(default=1.0, ge=0, allow_inf_nan=False)

    def to_weights(self) -> BM25Weights:
        """Build the BM25 weights."""
        from sci_etl_core.search.store_base import BM25Weights

        return BM25Weights(title=self.title, abstract=self.abstract, body=self.body)


class FusionConfig(BaseModel):
    """Rank fusion settings, as :class:`~sci_etl_core.search.fusion.FusionParams`."""

    k: int = Field(default=60, ge=1)
    weights: list[float] | None = None

    def to_params(self) -> FusionParams:
        """Build the fusion parameters.

        Raises:
            ValueError: A weight is negative or not finite.
        """
        from sci_etl_core.search.fusion import FusionParams

        return FusionParams(k=self.k, weights=None if self.weights is None else tuple(self.weights))


class HybridConfig(BaseModel):
    """Candidate pool sizes, as :class:`~sci_etl_core.search.hybrid_async.HybridParams`."""

    candidate_pool: int = Field(default=100, ge=1)
    chunk_pool_factor: int = Field(default=5, ge=1)

    def to_params(self) -> HybridParams:
        """Build the hybrid search parameters."""
        from sci_etl_core.search.hybrid_async import HybridParams

        return HybridParams(candidate_pool=self.candidate_pool, chunk_pool_factor=self.chunk_pool_factor)


class GraphConfig(BaseModel):
    """Discovery graph bounds, as :class:`~sci_etl_core.search.graph.GraphParams`."""

    depth: int = Field(default=2, ge=0)
    fanout: int = Field(default=8, ge=1)
    min_weight: float = Field(default=0.35, allow_inf_nan=False)
    max_nodes: int = Field(default=200, ge=1)
    mutual_only: bool = True
    max_iterations: int = Field(default=20, ge=1)

    def to_params(self) -> GraphParams:
        """Build the discovery graph parameters."""
        from sci_etl_core.search.graph import GraphParams

        return GraphParams(
            depth=self.depth,
            fanout=self.fanout,
            min_weight=self.min_weight,
            max_nodes=self.max_nodes,
            mutual_only=self.mutual_only,
            max_iterations=self.max_iterations,
        )


class SearchConfig(BaseModel):
    """Settings for local search and discovery graphs."""

    bm25: BM25WeightsConfig = Field(default_factory=BM25WeightsConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    hybrid: HybridConfig = Field(default_factory=HybridConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)


class BaseAppConfig(BaseModel):
    """Root of an application config: the library's sections, plus any keys a subclass adds.

    Unknown top-level keys are kept rather than rejected, so an application can
    read its own sections from the same YAML file. Subclass it to type those
    sections, and set ``extra="forbid"`` in the subclass to reject typos.
    """

    model_config = ConfigDict(extra="allow")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    full_text: RateLimitConfig = Field(default_factory=RateLimitConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML config file.

    Raises:
        ConfigurationError: The file is missing, is not valid YAML, or does not
            hold a mapping at the top level.
    """
    if not path.is_file():
        raise ConfigurationError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        text = handle.read()
    return parse_yaml(text, path)


def parse_yaml(text: str, source: Path) -> dict[str, Any]:
    """Parse YAML text that must hold a mapping; an empty document is ``{}``.

    Raises:
        ConfigurationError: The text is not valid YAML or its top level is not
            a mapping.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Config file is not valid YAML: {source}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"Config file must hold a mapping at the top level, not {type(raw).__name__}: {source}"
        )
    return raw


def apply_api_key(raw: dict[str, Any], api_key_env_var: str) -> dict[str, Any]:
    """Resolve the LLM API key, letting the environment override the YAML file.

    A key supplied at runtime through ``api_key_env_var`` always wins, so a
    stale or leaked key written into a config file can never silently replace
    it. The YAML value is only a fallback for when the variable is unset or
    empty. A non-mapping ``llm`` section is left for validation to reject.
    """
    llm = raw.get("llm")
    if llm is None:
        llm = raw["llm"] = {}
    if not isinstance(llm, dict):
        return raw
    env_key = os.getenv(api_key_env_var, "")
    if env_key:
        llm["api_key"] = env_key
    else:
        llm.setdefault("api_key", "")
    return raw


def load_config(
    config_cls: type[T],
    yaml_path: Path,
    env_path: Path | None = None,
    api_key_env_var: str = "LLM_API_KEY",
) -> T:
    """Load and validate a config from YAML plus a ``.env`` file.

    Without ``env_path``, ``.env`` is looked up from the current working
    directory upward, so the caller's project is searched rather than the
    location the library is installed in.

    Raises:
        ConfigurationError: The YAML file is missing or unreadable, or the
            configuration fails validation.
    """
    load_dotenv(env_path if env_path is not None else find_dotenv(usecwd=True))
    raw = apply_api_key(load_yaml(yaml_path), api_key_env_var)
    return validate_config(config_cls, raw, yaml_path)


def validate_config(config_cls: type[T], raw: dict[str, Any], source: Path) -> T:
    """Validate settings read from ``source`` against ``config_cls``.

    Raises:
        ConfigurationError: Validation failed. The message names each failing
            key and the reason but never the value that was read, so a secret
            such as an API key taken from the environment cannot reach a log or
            a terminal. The validation error is not chained for the same reason.
    """
    try:
        return config_cls.model_validate(raw)
    except ValidationError as exc:
        problems = [
            f"  {'.'.join(str(part) for part in detail['loc']) or '(top level)'}: {detail['msg']}"
            for detail in exc.errors(include_url=False, include_input=False)
        ]
        message = "\n".join([f"Invalid configuration in {source}:", *problems])
    except Exception as exc:
        message = f"Invalid configuration in {source}: {type(exc).__name__}: {exc}"
    raise ConfigurationError(message)
