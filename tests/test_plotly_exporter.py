from __future__ import annotations

import pandas as pd
import pytest

from sci_etl_core.exporters.plotly_exporter import Plotly3DExporter, ScatterPlotConfig


def _config():
    return ScatterPlotConfig(x_column="x", y_column="y", z_column="z", color_column="c")


class TestPlotly3DExporter:
    def test_noop_when_frame_empty_after_dropna(self, mocker):
        scatter = mocker.patch("sci_etl_core.exporters.plotly_exporter.px.scatter_3d")
        frame = pd.DataFrame({"x": [None], "y": [None], "z": [None], "c": ["a"]})
        Plotly3DExporter(_config()).export(frame, "out.html")
        scatter.assert_not_called()

    def test_writes_html_for_valid_frame(self, mocker):
        fig = mocker.MagicMock()
        scatter = mocker.patch("sci_etl_core.exporters.plotly_exporter.px.scatter_3d", return_value=fig)
        frame = pd.DataFrame({"x": [1.0], "y": [2.0], "z": [3.0], "c": ["a"]})
        Plotly3DExporter(_config()).export(frame, "out.html")
        scatter.assert_called_once()
        fig.update_layout.assert_called_once()
        fig.write_html.assert_called_once_with("out.html")

    def test_missing_required_column_raises(self):
        frame = pd.DataFrame({"x": [1.0], "y": [2.0]})
        with pytest.raises(KeyError):
            Plotly3DExporter(_config()).export(frame, "out.html")
