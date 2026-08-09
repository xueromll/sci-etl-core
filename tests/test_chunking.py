from __future__ import annotations

import sys
import types

from sci_etl_core.llm._chunking import truncate_to_tokens


class _FakeEncoding:
    def __init__(self, recorder: dict[str, object]) -> None:
        self._recorder = recorder

    def encode(self, text: str) -> list[str]:
        self._recorder["encoded"] = text
        return list(text)

    def decode(self, tokens: list[str]) -> str:
        return "".join(tokens)


def _fake_tiktoken(recorder: dict[str, object]) -> types.ModuleType:
    module = types.ModuleType("tiktoken")

    def get_encoding(name: str) -> _FakeEncoding:
        recorder["encoding_name"] = name
        return _FakeEncoding(recorder)

    module.get_encoding = get_encoding  # type: ignore[attr-defined]
    return module


def test_returns_none_when_tiktoken_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    assert truncate_to_tokens("hello world", max_tokens=5) is None


def test_returns_text_unchanged_when_within_limit(monkeypatch):
    recorder: dict[str, object] = {}
    monkeypatch.setitem(sys.modules, "tiktoken", _fake_tiktoken(recorder))
    assert truncate_to_tokens("hello", max_tokens=10) == "hello"
    assert recorder["encoded"] == "hello"


def test_truncates_text_when_over_limit(monkeypatch):
    recorder: dict[str, object] = {}
    monkeypatch.setitem(sys.modules, "tiktoken", _fake_tiktoken(recorder))
    assert truncate_to_tokens("hello world", max_tokens=5) == "hello"


def test_forwards_configured_encoding_name(monkeypatch):
    recorder: dict[str, object] = {}
    monkeypatch.setitem(sys.modules, "tiktoken", _fake_tiktoken(recorder))
    truncate_to_tokens("abc", max_tokens=1, encoding_name="p50k_base")
    assert recorder["encoding_name"] == "p50k_base"
