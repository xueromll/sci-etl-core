from __future__ import annotations

import httpx
import pandas as pd
import pytest

from sci_etl_core.config import BaseAppConfig
from sci_etl_core.exceptions import ConfigurationError
from sci_etl_core.exporters.plotly_async import ScatterPlotConfig


class TestAsyncConfig:
    @pytest.mark.asyncio
    async def test_loads_yaml_and_defaults(self, mocker, tmp_path):
        from sci_etl_core import config_async as ca

        mocker.patch.object(ca, "load_dotenv")
        mocker.patch.dict("os.environ", {"LLM_API_KEY": ""})
        path = tmp_path / "c.yaml"
        path.write_text("pipeline:\n  total_limit: 5\n", encoding="utf-8")
        cfg = await ca.load_config_async(BaseAppConfig, path)
        assert cfg.pipeline.total_limit == 5
        assert cfg.llm.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_env_api_key_applied(self, mocker, tmp_path):
        from sci_etl_core import config_async as ca

        mocker.patch.object(ca, "load_dotenv")
        mocker.patch.dict("os.environ", {"LLM_API_KEY": "secret"})
        path = tmp_path / "c.yaml"
        path.write_text("llm:\n  api_key: from-yaml\n", encoding="utf-8")
        cfg = await ca.load_config_async(BaseAppConfig, path)
        assert cfg.llm.api_key.get_secret_value() == "secret"

    @pytest.mark.asyncio
    async def test_missing_file_raises(self, mocker, tmp_path):
        from sci_etl_core import config_async as ca

        mocker.patch.object(ca, "load_dotenv")
        with pytest.raises(ConfigurationError, match="not found"):
            await ca.load_config_async(BaseAppConfig, tmp_path / "nope.yaml")

    @pytest.mark.asyncio
    async def test_invalid_configuration_raises(self, mocker, tmp_path):
        from sci_etl_core import config_async as ca

        mocker.patch.object(ca, "load_dotenv")
        mocker.patch.dict("os.environ", {"LLM_API_KEY": ""})
        path = tmp_path / "c.yaml"
        path.write_text("pipeline:\n  total_limit: not-an-int\n", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="Invalid configuration"):
            await ca.load_config_async(BaseAppConfig, path)


class TestAsyncHttpClient:
    def test_builds_async_client(self):
        from sci_etl_core.http_async import build_async_client

        client = build_async_client()
        assert isinstance(client, httpx.AsyncClient)


def _plotly_config():
    return ScatterPlotConfig(x_column="x", y_column="y", z_column="z", color_column="c")


class TestAsyncPlotlyExporter:
    @pytest.mark.asyncio
    async def test_writes_html_for_valid_frame(self, mocker, tmp_path):
        from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter

        fig = mocker.MagicMock()
        fig.to_html.return_value = "<html>fig</html>"
        mocker.patch("sci_etl_core.exporters.plotly_async.px.scatter_3d", return_value=fig)
        frame = pd.DataFrame({"x": [1.0], "y": [2.0], "z": [3.0], "c": ["a"]})
        dest = tmp_path / "o.html"
        await AsyncPlotly3DExporter(_plotly_config()).export(frame, str(dest))
        assert dest.read_text(encoding="utf-8").startswith("<html>")

    @pytest.mark.asyncio
    async def test_noop_when_frame_empty(self, mocker, tmp_path):
        from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter

        scatter = mocker.patch("sci_etl_core.exporters.plotly_async.px.scatter_3d")
        frame = pd.DataFrame({"x": [None], "y": [None], "z": [None], "c": ["a"]})
        dest = tmp_path / "o.html"
        await AsyncPlotly3DExporter(_plotly_config()).export(frame, str(dest))
        scatter.assert_not_called()
        assert not dest.exists()


class TestAsyncSqlExporter:
    @pytest.mark.asyncio
    async def test_writes_via_run_sync(self, mocker):
        from sci_etl_core.exporters.sql_async import AsyncSqlTableExporter

        connection = mocker.AsyncMock()
        begin_cm = mocker.MagicMock()
        begin_cm.__aenter__ = mocker.AsyncMock(return_value=connection)
        begin_cm.__aexit__ = mocker.AsyncMock(return_value=False)
        engine = mocker.Mock()
        engine.begin.return_value = begin_cm
        engine.dispose = mocker.AsyncMock()
        create = mocker.patch(
            "sci_etl_core.exporters.sql_async.create_async_engine", return_value=engine
        )
        frame = mocker.MagicMock(spec=pd.DataFrame)
        await AsyncSqlTableExporter(table_name="t", if_exists="replace").export(
            frame, "sqlite+aiosqlite:///:memory:"
        )
        create.assert_called_once_with("sqlite+aiosqlite:///:memory:")
        connection.run_sync.assert_awaited_once()
        engine.dispose.assert_awaited_once()


class TestAsyncPlotlyExporterStyling:
    @staticmethod
    def _frame():
        return pd.DataFrame(
            {
                "x": [1.0, 2.0],
                "y": [2.0, 3.0],
                "z": [3.0, 4.0],
                "fraction": [0.2, 0.9],
                "name": ["A", "B"],
                "note": ["first", "second"],
                "radius": [1.0, 4.0],
            }
        )

    @pytest.mark.asyncio
    async def test_real_figure_carries_hover_data_template_scale_range_and_label(self, mocker, tmp_path):
        from sci_etl_core.exporters import plotly_async

        config = ScatterPlotConfig(
            x_column="x",
            y_column="y",
            z_column="z",
            color_column="fraction",
            size_column="radius",
            hover_name_column="name",
            hover_data_columns=["note", "radius"],
            hover_template="<b>%{hovertext}</b> %{customdata[0]}<extra></extra>",
            color_continuous_scale="Viridis",
            color_range=(0.0, 1.0),
            color_label="DM Fraction",
            marker={"sizemode": "diameter", "sizemin": 3},
            layout={"paper_bgcolor": "#0b0f19", "scene": {"aspectmode": "cube"}},
        )
        scatter = mocker.spy(plotly_async.px, "scatter_3d")
        destination = tmp_path / "map.html"
        await plotly_async.AsyncPlotly3DExporter(config).export(self._frame(), str(destination))
        figure = scatter.spy_return
        trace = figure.data[0]
        assert [list(row) for row in trace.customdata] == [["first", 1.0], ["second", 4.0]]
        assert trace.hovertemplate == "<b>%{hovertext}</b> %{customdata[0]}<extra></extra>"
        assert trace.marker.sizemode == "diameter"
        assert trace.marker.sizemin == 3
        assert (figure.layout.coloraxis.cmin, figure.layout.coloraxis.cmax) == (0.0, 1.0)
        assert figure.layout.coloraxis.colorbar.title.text == "DM Fraction"
        assert figure.layout.coloraxis.colorscale[0][1] == "#440154"
        assert figure.layout.paper_bgcolor == "#0b0f19"
        assert figure.layout.scene.aspectmode == "cube"
        html = destination.read_text(encoding="utf-8").lstrip().lower()
        assert html.startswith(("<!doctype html>", "<html>"))
        assert html.rstrip().endswith("</html>")

    @pytest.mark.asyncio
    async def test_defaults_pass_no_styling_options(self, mocker, tmp_path):
        from sci_etl_core.exporters.plotly_async import AsyncPlotly3DExporter

        fig = mocker.MagicMock()
        fig.to_html.return_value = "<html></html>"
        scatter = mocker.patch("sci_etl_core.exporters.plotly_async.px.scatter_3d", return_value=fig)
        await AsyncPlotly3DExporter(_plotly_config()).export(self._frame().assign(c="a"), str(tmp_path / "o.html"))
        assert set(scatter.call_args.kwargs) == {"x", "y", "z", "color", "size", "hover_name", "title"}
        fig.update_traces.assert_not_called()
        fig.update_layout.assert_called_once()

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"color_range": (1.0, 0.0)}, "must be increasing"),
            ({"color_range": (0.0, 0.0)}, "must be increasing"),
            ({"color_range": (0.0, float("inf"))}, "two finite numbers"),
            ({"color_range": (0.0,)}, "two finite numbers"),
            ({"hover_data_columns": ["a", "a"]}, "repeats a column"),
        ],
    )
    def test_rejects_invalid_styling(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            ScatterPlotConfig(x_column="x", y_column="y", z_column="z", color_column="c", **kwargs)
