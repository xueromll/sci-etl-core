from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TypeVar

from sci_etl_core.config import BaseAppConfig, apply_api_key, load_env_file, parse_yaml, validate_config
from sci_etl_core.exceptions import ConfigurationError

T = TypeVar("T", bound=BaseAppConfig)


async def load_yaml_async(path: Path) -> dict[str, Any]:
    """Read a YAML config file without blocking the event loop.

    Raises:
        ConfigurationError: The file is missing, is not valid YAML, or does not
            hold a mapping at the top level.
    """
    if not await asyncio.to_thread(Path(path).is_file):
        raise ConfigurationError(f"Config file not found: {path}")
    text = await asyncio.to_thread(Path(path).read_text, encoding="utf-8")
    return parse_yaml(text, Path(path))


async def load_config_async(
    config_cls: type[T],
    yaml_path: Path,
    env_path: Path | None = None,
    api_key_env_var: str = "LLM_API_KEY",
    *,
    load_env: bool = False,
) -> T:
    """Async counterpart of :func:`sci_etl_core.config.load_config`, with the same lookup rules."""
    await asyncio.to_thread(load_env_file, env_path, load_env=load_env)
    raw = apply_api_key(await load_yaml_async(yaml_path), api_key_env_var)
    return validate_config(config_cls, raw, Path(yaml_path))
