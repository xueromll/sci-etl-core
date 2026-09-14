from __future__ import annotations

import os
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
        mocker.patch.object(config_module, "find_dotenv", return_value="/project/.env")
        mocker.patch.object(config_module, "load_yaml", return_value={})
        mocker.patch.object(config_module.os, "getenv", return_value="")
        cfg = load_config(BaseAppConfig, Path("missing.yaml"))
        assert cfg.pipeline.max_records == 100
        assert cfg.llm.model == "gpt-4o-mini"
        assert cfg.llm.api_key.get_secret_value() == ""
        config_module.find_dotenv.assert_called_once_with(usecwd=True)
        config_module.load_dotenv.assert_called_once_with("/project/.env")

    def test_dotenv_is_searched_from_the_working_directory(self, monkeypatch, tmp_path):
        (tmp_path / ".env").write_text("SCI_ETL_CWD_TEST_KEY=from-cwd\n", encoding="utf-8")
        (tmp_path / "config.yaml").write_text("llm:\n  model: m\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        try:
            cfg = load_config(BaseAppConfig, Path("config.yaml"), api_key_env_var="SCI_ETL_CWD_TEST_KEY")
            assert cfg.llm.api_key.get_secret_value() == "from-cwd"
        finally:
            os.environ.pop("SCI_ETL_CWD_TEST_KEY", None)

    def test_yaml_syntax_error_is_a_configuration_error(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_text("llm: [unclosed\n", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="not valid YAML"):
            load_yaml(path)

    @pytest.mark.parametrize("text", ["- a\n- b\n", "just a string\n", "42\n"])
    def test_non_mapping_document_is_a_configuration_error(self, tmp_path, text):
        path = tmp_path / "c.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ConfigurationError, match="mapping"):
            load_yaml(path)

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

    def test_pipeline_section_carries_page_size_and_search_delay(self, mocker):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(
            config_module, "load_yaml", return_value={"pipeline": {"page_size": 25, "search_delay": 0}}
        )
        mocker.patch.object(config_module.os, "getenv", return_value="")
        cfg = load_config(BaseAppConfig, Path("c.yaml"))
        assert (cfg.pipeline.page_size, cfg.pipeline.search_delay) == (25, 0)

    @pytest.mark.parametrize(
        "raw",
        [
            {"pipeline": {"max_workers": 0}},
            {"pipeline": {"page_size": 0}},
            {"pipeline": {"max_records": -1}},
            {"pipeline": {"sleep_between": -1}},
            {"pipeline": {"search_delay": -0.5}},
            {"http": {"max_retries": 0}},
            {"http": {"backoff_factor": -1}},
            {"http": {"timeout": 0}},
            {"llm": {"timeout": 0}},
            {"full_text": {"max_concurrency": 0}},
            {"full_text": {"max_rate": 0}},
            {"full_text": {"time_period": 0}},
        ],
    )
    def test_out_of_range_values_are_configuration_errors(self, mocker, raw):
        mocker.patch.object(config_module, "load_dotenv")
        mocker.patch.object(config_module, "load_yaml", return_value=raw)
        mocker.patch.object(config_module.os, "getenv", return_value="")
        with pytest.raises(ConfigurationError, match="Invalid configuration"):
            load_config(BaseAppConfig, Path("c.yaml"))
