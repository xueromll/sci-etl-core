from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import aiofiles
import pandas as pd
import plotly.express as px

from sci_etl_core.exporters.async_base import AsyncExporter


@dataclass(slots=True)
class ScatterPlotConfig:
    """What an :class:`AsyncPlotly3DExporter` plots and how it looks.

    ``hover_data_columns`` are passed to the figure as custom data, so
    ``hover_template`` can show them as ``%{customdata[0]}``, ``%{customdata[1]}``,
    and so on, in the order listed; the ``hover_name_column`` value is
    ``%{hovertext}``. A numeric ``color_column`` is drawn with
    ``color_continuous_scale``, such as ``"Viridis"``, over ``color_range``
    when one is given, so colors mean the same in every export regardless of
    the values present. ``color_label`` names the color bar or legend.
    ``marker`` is applied to every trace's marker, such as
    ``{"sizemode": "diameter", "sizemin": 3}``, and ``layout`` is applied to the
    figure layout last, overriding ``template`` and the default margins.

    Raises:
        ValueError: ``color_range`` does not hold two finite numbers in
            increasing order, or ``hover_data_columns`` repeats a column.
    """

    x_column: str
    y_column: str
    z_column: str
    color_column: str
    size_column: str | None = None
    hover_name_column: str | None = None
    title: str = "3D Scatter"
    template: str = "plotly_dark"
    hover_data_columns: Sequence[str] = ()
    hover_template: str | None = None
    color_continuous_scale: str | Sequence[str] | None = None
    color_range: tuple[float, float] | None = None
    color_label: str | None = None
    marker: Mapping[str, Any] = field(default_factory=dict)
    layout: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.color_range is not None:
            if len(self.color_range) != 2 or not all(math.isfinite(bound) for bound in self.color_range):
                raise ValueError("color_range must hold two finite numbers")
            if self.color_range[0] >= self.color_range[1]:
                raise ValueError("color_range must be increasing")
        self.hover_data_columns = tuple(self.hover_data_columns)
        if len(set(self.hover_data_columns)) != len(self.hover_data_columns):
            raise ValueError("hover_data_columns repeats a column")


class AsyncPlotly3DExporter(AsyncExporter):
    """Write a DataFrame as an interactive 3D scatter plot in a standalone HTML file.

    Rows missing an x, y, or z value are left out, and nothing is written when
    no row remains.
    """

    def __init__(self, config: ScatterPlotConfig) -> None:
        self._config = config

    async def export(self, data: pd.DataFrame, destination: str) -> None:
        html = await asyncio.to_thread(self._render, data)
        if html is None:
            return
        async with aiofiles.open(destination, "w", encoding="utf-8") as handle:
            await handle.write(html)

    def _render(self, data: pd.DataFrame) -> str | None:
        config = self._config
        frame = data.dropna(subset=[config.x_column, config.y_column, config.z_column])
        if frame.empty:
            return None
        options: dict[str, Any] = {}
        if config.hover_data_columns:
            options["custom_data"] = list(config.hover_data_columns)
        if config.color_continuous_scale is not None:
            options["color_continuous_scale"] = config.color_continuous_scale
        if config.color_range is not None:
            options["range_color"] = list(config.color_range)
        if config.color_label is not None:
            options["labels"] = {config.color_column: config.color_label}
        fig = px.scatter_3d(
            frame,
            x=config.x_column,
            y=config.y_column,
            z=config.z_column,
            color=config.color_column,
            size=config.size_column,
            hover_name=config.hover_name_column,
            title=config.title,
            **options,
        )
        trace_updates: dict[str, Any] = {}
        if config.marker:
            trace_updates["marker"] = dict(config.marker)
        if config.hover_template is not None:
            trace_updates["hovertemplate"] = config.hover_template
        if trace_updates:
            fig.update_traces(**trace_updates)
        fig.update_layout(template=config.template, margin=dict(l=0, r=0, b=0, t=50))
        if config.layout:
            fig.update_layout(**dict(config.layout))
        return fig.to_html()
