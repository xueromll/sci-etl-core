from __future__ import annotations

from pydantic import SecretStr


def reveal_secret(api_key: str | SecretStr) -> str:
    """Return the plain-text API key, unwrapping ``SecretStr`` when needed."""
    return api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
