from __future__ import annotations

import asyncio

import aiofiles
import pandas as pd

from sci_etl_core._deprecation import warn_deprecated
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.processors.sinks import ScatterPlotConfig, render_scatter_3d

__all__ = ["AsyncPlotly3DExporter", "ScatterPlotConfig"]


class AsyncPlotly3DExporter(AsyncExporter):
    """Write a DataFrame as an interactive 3D scatter plot in a standalone HTML file.

    Rows missing an x, y, or z value are left out, and nothing is written when
    no row remains.

    .. deprecated:: 0.5.0
        Constructing it emits a :class:`DeprecationWarning`. It will be
        removed in 0.6.0; use
        :class:`~sci_etl_core.processors.sinks.Plotly3DSink` instead.
    """

    def __init__(self, config: ScatterPlotConfig) -> None:
        warn_deprecated("AsyncPlotly3DExporter", "use sci_etl_core.processors.sinks.Plotly3DSink instead")
        self._config = config

    async def export(self, data: pd.DataFrame, destination: str) -> None:
        html = await asyncio.to_thread(render_scatter_3d, data, self._config)
        if html is None:
            return
        async with aiofiles.open(destination, "w", encoding="utf-8") as handle:
            await handle.write(html)
