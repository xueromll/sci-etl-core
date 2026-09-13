from __future__ import annotations

import pytest

from sci_etl_core import config_async
from sci_etl_core.config import BaseAppConfig
from sci_etl_core.exceptions import ConfigurationError
from sci_etl_core.http_async import build_async_client


class TestAsyncConfigErrors:
    @pytest.mark.parametrize(
        "text, message",
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
