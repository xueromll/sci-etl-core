from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import pytest

from sci_etl_core import _user_agent, config_async
from sci_etl_core.config import BaseAppConfig, HttpConfig
from sci_etl_core.exceptions import ConfigurationError
from sci_etl_core.http_async import build_async_client


class TestAsyncConfigErrors:
    @pytest.mark.parametrize(
        ("text", "message"),
        [("llm: [unclosed\n", "not valid YAML"), ("- a\n- b\n", "mapping")],
    )
    @pytest.mark.asyncio
    async def test_unusable_yaml_raises_configuration_error(self, mocker, tmp_path, text, message):
        mocker.patch.object(config_async, "load_dotenv")
        path = tmp_path / "c.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ConfigurationError, match=message):
            await config_async.load_config_async(BaseAppConfig, path)

    @pytest.mark.asyncio
    async def test_invalid_values_are_reported_by_key(self, mocker, tmp_path):
        mocker.patch.object(config_async, "load_dotenv")
        path = tmp_path / "c.yaml"
        path.write_text("pipeline:\n  max_concurrency: 0\n", encoding="utf-8")
        expected = r"pipeline\.max_concurrency: Input should be greater than or equal to 1"
        with pytest.raises(ConfigurationError, match=expected):
            await config_async.load_config_async(BaseAppConfig, path)

    @pytest.mark.asyncio
    async def test_dotenv_lookup_starts_at_the_working_directory(self, mocker, tmp_path):
        load = mocker.patch.object(config_async, "load_dotenv")
        find = mocker.patch.object(config_async, "find_dotenv", return_value="/project/.env")
        path = tmp_path / "c.yaml"
        path.write_text("", encoding="utf-8")
        await config_async.load_config_async(BaseAppConfig, path)
        find.assert_called_once_with(usecwd=True)
        load.assert_called_once_with("/project/.env")


class TestAsyncClientDefaults:
    @pytest.mark.asyncio
    async def test_client_follows_redirects(self):
        client = build_async_client()
        try:
            assert client.follow_redirects is True
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_default_user_agent_reports_the_installed_version(self):
        client = build_async_client()
        try:
            assert client.headers["User-Agent"] == f"sci-etl-core/{version('sci-etl-core')}"
        finally:
            await client.aclose()


class TestDefaultUserAgent:
    def test_http_config_defaults_to_the_installed_version(self):
        assert HttpConfig().user_agent == f"sci-etl-core/{version('sci-etl-core')}"

    def test_missing_distribution_falls_back_to_the_bare_name(self, mocker):
        mocker.patch.object(_user_agent, "version", side_effect=PackageNotFoundError("sci-etl-core"))
        assert _user_agent.default_user_agent() == "sci-etl-core"
