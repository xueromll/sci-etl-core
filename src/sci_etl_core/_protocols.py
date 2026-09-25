from __future__ import annotations

from typing import Protocol, runtime_checkable

from sci_etl_core.models import TokenUsage


@runtime_checkable
class SupportsAclose(Protocol):
    """A resource the pipeline closes when ``async with pipeline`` exits."""

    async def aclose(self) -> None: ...


@runtime_checkable
class UsageReporter(Protocol):
    """A client that reports the tokens it has used, such as an LLM client or an embedder."""

    @property
    def usage(self) -> TokenUsage | None: ...
