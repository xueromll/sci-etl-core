from __future__ import annotations

from pathlib import Path

import pytest

from sci_etl_core import config as config_module
from sci_etl_core.config import BaseAppConfig, load_config, load_yaml
from sci_etl_core.exceptions import ConfigurationError


class TestLoadYaml:
    def test_missing_file_raises_configuration_error(self, mocker):
        path = mocker.Mock(spec=Path)
        path.is_file.return_value = False
        with pytest.raises(ConfigurationError, match="not found"):
            load_yaml(path)

    def test_reads_and_parses_existing_file(self, mocker):
        path = mocker.Mock(spec=Path)
        path.is_file.return_value = True
        path.open = mocker.mock_open(read_data="pipeline:\n  max_records: 5\n")
        assert load_yaml(path)["pipeline"]["max_records"] == 5

    def test_empty_file_returns_empty_dict(self, mocker):
        path = mocker.Mock(spec=Path)
        path.is_file.return_value = True
        path.open = mocker.mock_open(read_data="")
        assert load_yaml(path) == {}


class TestLoadConfig:
    def test_uses_defaults_when_yaml_empty_and_no_env(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={})
        mocker.patch.object(config_module.os, "getenv", return_value="")
        cfg = load_config(BaseAppConfig, Path("missing.yaml"))
        assert cfg.pipeline.max_records == 100
        assert cfg.llm.model == "gpt-4o-mini"
        assert cfg.llm.api_key.get_secret_value() == ""
        config_module.load_dotenv.assert_called_once_with()

    def test_env_path_is_forwarded_to_dotenv(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={})
        mocker.patch.object(config_module.os, "getenv", return_value="secret")
        env = Path(".env")
        cfg = load_config(BaseAppConfig, Path("c.yaml"), env_path=env)
        config_module.load_dotenv.assert_called_once_with(env)
        assert cfg.llm.api_key.get_secret_value() == "secret"

    def test_env_api_key_takes_precedence_over_yaml(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={"llm": {"api_key": "from-yaml"}})
        mocker.patch.object(config_module.os, "getenv", return_value="from-env")
        cfg = load_config(BaseAppConfig, Path("c.yaml"))
        assert cfg.llm.api_key.get_secret_value() == "from-env"

    def test_yaml_api_key_is_a_fallback_when_env_is_unset(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={"llm": {"api_key": "from-yaml"}})
        mocker.patch.object(config_module.os, "getenv", return_value="")
        cfg = load_config(BaseAppConfig, Path("c.yaml"))
        assert cfg.llm.api_key.get_secret_value() == "from-yaml"

    def test_null_llm_section_still_receives_the_env_key(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={"llm": None})
        mocker.patch.object(config_module.os, "getenv", return_value="from-env")
        cfg = load_config(BaseAppConfig, Path("c.yaml"))
        assert cfg.llm.api_key.get_secret_value() == "from-env"

    def test_non_mapping_llm_section_is_rejected(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={"llm": "oops"})
        mocker.patch.object(config_module.os, "getenv", return_value="from-env")
        with pytest.raises(ConfigurationError, match="Invalid configuration"):
            load_config(BaseAppConfig, Path("c.yaml"))

    def test_secret_is_hidden_in_repr(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={"llm": {"api_key": "top-secret"}})
        mocker.patch.object(config_module.os, "getenv", return_value="")
        cfg = load_config(BaseAppConfig, Path("c.yaml"))
        assert "top-secret" not in repr(cfg.llm)

    def test_invalid_configuration_raises(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value={"pipeline": {"max_records": "not-an-int"}})
        mocker.patch.object(config_module.os, "getenv", return_value="")
        with pytest.raises(ConfigurationError, match="Invalid configuration"):
            load_config(BaseAppConfig, Path("c.yaml"))
