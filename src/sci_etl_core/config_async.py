from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import aiofiles
import yaml
from dotenv import load_dotenv

from sci_etl_core.config import BaseAppConfig, apply_api_key
from sci_etl_core.exceptions import ConfigurationError

T = TypeVar("T", bound=BaseAppConfig)


async def load_yaml_async(path: Path) -> dict[str, Any]:
    if not Path(path).is_file():
        raise ConfigurationError(f"Config file not found: {path}")
    async with aiofiles.open(path, "r", encoding="utf-8") as handle:
        text = await handle.read()
    return yaml.safe_load(text) or {}


async def load_config_async(
    config_cls: type[T],
    yaml_path: Path,
    env_path: Path | None = None,
    api_key_env_var: str = "LLM_API_KEY",
) -> T:
    load_dotenv(env_path) if env_path else load_dotenv()
    raw = apply_api_key(await load_yaml_async(yaml_path), api_key_env_var)
    try:
        return config_cls.model_validate(raw)
    except Exception as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc
