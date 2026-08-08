from __future__ import annotations

import asyncio

import aiofiles
import pandas as pd
import plotly.express as px

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.exporters.plotly_exporter import ScatterPlotConfig


class AsyncPlotly3DExporter(AsyncExporter):
    def __init__(self, config: ScatterPlotConfig) -> None:
        self._config = config

    async def export(self, data: pd.DataFrame, destination: str) -> None:
        html = await asyncio.to_thread(self._render, data)
        if html is None:
            return
        async with aiofiles.open(destination, "w", encoding="utf-8") as handle:
            await handle.write(html)

    def _render(self, data: pd.DataFrame) -> str | None:
        frame = data.dropna(subset=[self._config.x_column, self._config.y_column, self._config.z_column])
        if frame.empty:
            return None

        fig = px.scatter_3d(
            frame,
            x=self._config.x_column,
            y=self._config.y_column,
            z=self._config.z_column,
            color=self._config.color_column,
            size=self._config.size_column,
            hover_name=self._config.hover_name_column,
            title=self._config.title,
        )
        fig.update_layout(template=self._config.template, margin=dict(l=0, r=0, b=0, t=50))
        return fig.to_html()
