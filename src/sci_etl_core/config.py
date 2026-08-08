from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from sci_etl_core.exceptions import ConfigurationError

T = TypeVar("T", bound="BaseAppConfig")


class LLMConfig(BaseModel):
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: int = 120


class HttpConfig(BaseModel):
    user_agent: str = "sci-etl-core/0.1"
    max_retries: int = 3
    backoff_factor: float = 2.0
    timeout: int = 25


class PipelineConfig(BaseModel):
    search_query: str = ""
    max_records: int = 100
    sleep_between: float = 5.0
    max_workers: int = 6


class BaseAppConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config(
    config_cls: type[T],
    yaml_path: Path,
    env_path: Path | None = None,
    api_key_env_var: str = "LLM_API_KEY",
) -> T:
    load_dotenv(env_path) if env_path else load_dotenv()
    raw = load_yaml(yaml_path)
    raw.setdefault("llm", {})
    raw["llm"].setdefault("api_key", os.getenv(api_key_env_var, ""))
    try:
        return config_cls.model_validate(raw)
    except Exception as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc
