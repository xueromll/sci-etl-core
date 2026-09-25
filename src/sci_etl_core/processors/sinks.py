"""Destinations for a post-processed table.

Importing this module needs the ``processors`` extra (pandas). Constructing
:class:`SqlTableSink` also needs the ``sql`` extra, and :class:`Plotly3DSink`
the ``viz`` extra; each imports its library when constructed, so importing
this module never fails for a missing optional library.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

from sci_etl_core._atomic_io import atomic_write_text


class TableSink(ABC):
    """A blocking destination for the table a :class:`~sci_etl_core.processors.base.ProcessorChain` produced.

    Call :meth:`write` once the table is final, for example through
    ``asyncio.to_thread`` from async code.
    """

    @abstractmethod
    def write(self, frame: pd.DataFrame) -> None:
        """Store ``frame``."""


class SqlTableSink(TableSink):
    """Write a table to a SQL database through SQLAlchemy. Needs the ``sql`` extra.

    ``url`` is a synchronous SQLAlchemy database URL, such as
    ``"sqlite:///catalogue.db"``, and ``if_exists`` is passed to
    ``DataFrame.to_sql``. Each :meth:`write` creates an engine, writes the
    table without its index in one transaction, and disposes of the engine.

    Raises:
        ImportError: SQLAlchemy is not installed.
    """

    def __init__(self, url: str, table_name: str, if_exists: str = "append") -> None:
        self._sqlalchemy = import_module("sqlalchemy")
        self._url = url
        self._table_name = table_name
        self._if_exists = if_exists

    def write(self, frame: pd.DataFrame) -> None:
        engine = self._sqlalchemy.create_engine(self._url)
        try:
            with engine.begin() as connection:
                frame.to_sql(self._table_name, connection, if_exists=self._if_exists, index=False)
        finally:
            engine.dispose()


@dataclass(slots=True)
class ScatterPlotConfig:
    """What a 3D scatter plot shows and how it looks.

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


def render_scatter_3d(frame: pd.DataFrame, config: ScatterPlotConfig) -> str | None:
    """Render ``frame`` as a standalone HTML 3D scatter plot, or return ``None`` when no row has x, y, and z.

    Needs the ``viz`` extra.
    """
    express = import_module("plotly.express")
    rows = frame.dropna(subset=[config.x_column, config.y_column, config.z_column])
    if rows.empty:
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
    fig = express.scatter_3d(
        rows,
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
    return str(fig.to_html())


class Plotly3DSink(TableSink):
    """Write a table as an interactive 3D scatter plot in a standalone HTML file. Needs the ``viz`` extra.

    Rows missing an x, y, or z value are left out, and nothing is written when
    no row remains. The file is replaced atomically.

    Raises:
        ImportError: Plotly is not installed.
    """

    def __init__(self, config: ScatterPlotConfig, path: str | Path) -> None:
        import_module("plotly.express")
        self._config = config
        self._path = Path(path)

    def write(self, frame: pd.DataFrame) -> None:
        html = render_scatter_3d(frame, self._config)
        if html is not None:
            atomic_write_text(self._path, html)
