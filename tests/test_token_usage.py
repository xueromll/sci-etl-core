from __future__ import annotations

from types import SimpleNamespace

from sci_etl_core import TokenUsage
from sci_etl_core.embeddings.async_base import AsyncEmbedder
from sci_etl_core.llm.async_base import AsyncLLMClient


def test_record_adds_reported_tokens_and_counts_every_request():
    usage = TokenUsage()
    usage.record(SimpleNamespace(prompt_tokens=120, completion_tokens=8))
    usage.record(SimpleNamespace(prompt_tokens=30, total_tokens=30))
    usage.record(None)
    assert usage == TokenUsage(requests=3, prompt_tokens=150, completion_tokens=8)
    assert usage.total_tokens == 158


def test_values_that_are_not_token_counts_are_ignored():
    usage = TokenUsage()
    usage.record(SimpleNamespace(prompt_tokens=True, completion_tokens=-4))
    usage.record(SimpleNamespace(prompt_tokens="12", completion_tokens=2.5))
    assert usage == TokenUsage(requests=2)


def test_clients_that_do_not_track_usage_report_none():
    class EchoClient(AsyncLLMClient):
        async def complete_json(self, system_prompt, user_content, timeout=None):  # noqa: ASYNC109
            return {}

    class ZeroEmbedder(AsyncEmbedder):
        async def embed(self, texts):
            return [[0.0] for _ in texts]

    assert EchoClient().usage is None
    assert ZeroEmbedder().usage is None
