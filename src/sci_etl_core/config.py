from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from sci_etl_core.exceptions import ConfigurationError

T = TypeVar("T", bound="BaseAppConfig")


class LLMConfig(BaseModel):
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: int = Field(default=120, gt=0)


class HttpConfig(BaseModel):
    user_agent: str = "sci-etl-core/0.1"
    max_retries: int = Field(default=3, ge=1)
    backoff_factor: float = Field(default=2.0, ge=0)
    timeout: int = Field(default=25, gt=0)


class RateLimitConfig(BaseModel):
    max_concurrency: int = Field(default=4, ge=1)
    max_rate: float | None = Field(default=None, gt=0)
    time_period: float = Field(default=1.0, gt=0)


class PipelineConfig(BaseModel):
    search_query: str = ""
    max_records: int = Field(default=100, ge=0)
    page_size: int = Field(default=100, ge=1)
    search_delay: float = Field(default=3.0, ge=0)
    sleep_between: float = Field(default=5.0, ge=0)
    max_workers: int = Field(default=6, ge=1)


class BaseAppConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    full_text: RateLimitConfig = Field(default_factory=RateLimitConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


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
