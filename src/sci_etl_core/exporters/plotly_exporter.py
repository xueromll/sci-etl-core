from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.express as px

from sci_etl_core.exporters.base import Exporter


@dataclass(slots=True)
class ScatterPlotConfig:
    x_column: str
    y_column: str
    z_column: str
    color_column: str
    size_column: str | None = None
    hover_name_column: str | None = None
    title: str = "3D Scatter"
    template: str = "plotly_dark"


class Plotly3DExporter(Exporter):
    def __init__(self, config: ScatterPlotConfig) -> None:
        self._config = config

    def export(self, data: pd.DataFrame, destination: str) -> None:
        frame = data.dropna(subset=[self._config.x_column, self._config.y_column, self._config.z_column])
        if frame.empty:
            return

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
        fig.write_html(destination)
