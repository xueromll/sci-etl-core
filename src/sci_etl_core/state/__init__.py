from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "AsyncFileStateManager": "sci_etl_core.state.async_file_state",
    "AsyncSqliteStateManager": "sci_etl_core.state.sqlite_async",
    "AsyncStateManager": "sci_etl_core.state.async_base",
    "StateManager": "sci_etl_core.state.base",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.state.async_file_state import AsyncFileStateManager
    from sci_etl_core.state.sqlite_async import AsyncSqliteStateManager
    from sci_etl_core.state.async_base import AsyncStateManager
    from sci_etl_core.state.base import StateManager
