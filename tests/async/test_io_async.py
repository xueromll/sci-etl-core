from __future__ import annotations

import httpx
import pandas as pd
import pytest

from sci_etl_core.config import BaseAppConfig
from sci_etl_core.exceptions import ConfigurationError
from sci_etl_core.exporters.plotly_exporter import ScatterPlotConfig


class TestAsyncConfig:
    @pytest.mark.asyncio
    async def test_loads_yaml_and_defaults(self, mocker, tmp_path):
        from sci_etl_core import config_async as ca

        mocker.patch.object(ca, "load_dotenv")
        mocker.patch.object(ca.os, "getenv", return_value="")
        path = tmp_path / "c.yaml"
        path.write_text("pipeline:\n  max_records: 5\n", encoding="utf-8")
        cfg = await ca.load_config_async(BaseAppConfig, path)
        assert cfg.pipeline.max_records == 5
        assert cfg.llm.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_env_api_key_applied(self, mocker, tmp_path):
        from sci_etl_core import config_async as ca

        mocker.patch.object(ca, "load_dotenv")
        mocker.patch.object(ca.os, "getenv", return_value="secret")
        path = tmp_path / "c.yaml"
        path.write_text("", encoding="utf-8")
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
        mocker.patch.object(ca.os, "getenv", return_value="")
        path = tmp_path / "c.yaml"
        path.write_text("pipeline:\n  max_records: not-an-int\n", encoding="utf-8")
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
