from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_DISTRIBUTION = "sci-etl-core"


def default_user_agent() -> str:
    """Return ``sci-etl-core/<installed version>``, or ``sci-etl-core`` when no distribution is installed."""
    try:
        return f"{_DISTRIBUTION}/{version(_DISTRIBUTION)}"
    except PackageNotFoundError:
        return _DISTRIBUTION


DEFAULT_USER_AGENT = default_user_agent()
