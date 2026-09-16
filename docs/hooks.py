"""MkDocs hooks that assemble the sci-etl-core site.

Two jobs happen here:

- The CLI documentation lives in the sci-etl-cli repository. Its ``docs/``
  pages are mounted under ``cli/`` and its ``nav`` replaces the ``CLI`` entry of
  this site's navigation. The checkout is read from ``SCI_ETL_CLI_DIR`` or, by
  default, a ``sci-etl-cli`` folder beside this repository.
- Project files such as ``CHANGELOG.md`` stay at the repository root, where
  GitHub shows them. A page whose whole body is ``--8<-- "NAME.md"`` renders
  that file, with its relative links pointing at the matching site pages or,
  for files the site doesn't publish, at GitHub.
"""

from __future__ import annotations

import logging
import os
import posixpath
import re
from pathlib import Path
from typing import Any

import yaml
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.livereload import LiveReloadServer
from mkdocs.structure.files import File, Files
from mkdocs.structure.pages import Page

CLI_SECTION = "CLI"
CLI_PREFIX = "cli"
CLI_DIR_VARIABLE = "SCI_ETL_CLI_DIR"
DEFAULT_BRANCH = "master"

ROOT_INCLUDE = re.compile(r'\A\s*--8<-- "(?P<name>[\w.-]+)"\s*\Z')
RELATIVE_LINK = re.compile(r"\]\((?!https?:|mailto:|#)(?P<target>[^)#\s]+)(?P<anchor>#[^)\s]*)?\)")

log = logging.getLogger("mkdocs.hooks.sci_etl")

_root_pages: dict[str, str] = {}


def on_config(config: MkDocsConfig) -> MkDocsConfig:
    cli_nav = _cli_nav(_cli_dir(config))
    nav: list[Any] = []
    for item in config.nav or []:
        if not _is_cli_entry(item):
            nav.append(item)
        elif cli_nav is not None:
            nav.append({CLI_SECTION: cli_nav})
    config.nav = nav
    return config


def on_files(files: Files, config: MkDocsConfig) -> Files:
    cli_docs = _cli_dir(config) / "docs"
    if cli_docs.is_dir():
        for source in sorted(path for path in cli_docs.rglob("*") if path.is_file()):
            uri = posixpath.join(CLI_PREFIX, source.relative_to(cli_docs).as_posix())
            files.append(File.generated(config, uri, abs_src_path=str(source)))
    _root_pages.clear()
    for file in files.documentation_pages():
        if file.abs_src_path is None:
            continue
        match = ROOT_INCLUDE.match(Path(file.abs_src_path).read_text(encoding="utf-8"))
        if match is not None:
            _root_pages[match["name"]] = file.src_uri
    return files


def on_page_markdown(markdown: str, page: Page, config: MkDocsConfig, files: Files) -> str | None:
    match = ROOT_INCLUDE.match(markdown)
    if match is None:
        return None
    source = _repository_root(config) / match["name"]
    blob_base = f"{(config.repo_url or '').rstrip('/')}/blob/{DEFAULT_BRANCH}/"

    def rewrite(link: re.Match[str]) -> str:
        target, anchor = link["target"], link["anchor"] or ""
        site_page = _root_pages.get(target)
        if site_page is None:
            return f"]({blob_base}{target}{anchor})"
        relative = posixpath.relpath(site_page, posixpath.dirname(page.file.src_uri) or ".")
        return f"]({relative}{anchor})"

    return RELATIVE_LINK.sub(rewrite, source.read_text(encoding="utf-8"))


def on_serve(server: LiveReloadServer, config: MkDocsConfig, builder: Any) -> LiveReloadServer:
    cli_dir = _cli_dir(config)
    for path in (cli_dir / "docs", cli_dir / "mkdocs.yml"):
        if path.exists():
            server.watch(str(path))
    for name in _root_pages:
        server.watch(str(_repository_root(config) / name))
    return server


def _repository_root(config: MkDocsConfig) -> Path:
    return Path(config.config_file_path).resolve().parent


def _cli_dir(config: MkDocsConfig) -> Path:
    configured = os.environ.get(CLI_DIR_VARIABLE)
    if configured:
        return Path(configured).resolve()
    return _repository_root(config).parent / "sci-etl-cli"


def _cli_nav(cli_dir: Path) -> list[Any] | None:
    cli_config = cli_dir / "mkdocs.yml"
    if not cli_config.is_file():
        log.warning(
            "No sci-etl-cli checkout at %s, so the CLI section is left out. "
            "Clone sci-etl-cli beside this repository or set %s.",
            cli_dir,
            CLI_DIR_VARIABLE,
        )
        return None
    with cli_config.open(encoding="utf-8") as handle:
        return [_prefixed(item) for item in yaml.safe_load(handle)["nav"]]


def _prefixed(item: Any) -> Any:
    if isinstance(item, str):
        return posixpath.join(CLI_PREFIX, item)
    if isinstance(item, list):
        return [_prefixed(child) for child in item]
    return {title: _prefixed(value) for title, value in item.items()}


def _is_cli_entry(item: Any) -> bool:
    return isinstance(item, dict) and CLI_SECTION in item
