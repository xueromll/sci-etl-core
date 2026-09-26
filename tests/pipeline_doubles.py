"""Entity extractor and exporter doubles for pipeline tests that script their collaborators with mocks.

A ``Mock(spec=AsyncEntityExtractor)`` would give ``extract_record``, the method
the pipeline calls, its own mock. :func:`entity_extractor` returns a real
extractor instead, whose ``extract`` is an ``AsyncMock`` a test can replace,
so the default ``extract_record`` still reaches it.
"""

from __future__ import annotations

from typing import Any

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor


class ScriptedEntities(AsyncEntityExtractor[Any]):
    async def extract(self, text: str | bytes) -> list[Any]:
        return []


def entity_extractor(mocker: Any, entities: Any = None, **mock_options: Any) -> Any:
    extractor = ScriptedEntities()
    if mock_options:
        extractor.extract = mocker.AsyncMock(**mock_options)
    else:
        extractor.extract = mocker.AsyncMock(return_value=[{"name": "X"}] if entities is None else entities)
    return extractor


def exporter(mocker: Any, *, durable_writes: bool = True) -> Any:
    double = mocker.Mock(spec=AsyncExporter)
    double.durable_writes = durable_writes
    for name in ("open", "write", "flush", "aclose"):
        setattr(double, name, mocker.AsyncMock())
    return double
