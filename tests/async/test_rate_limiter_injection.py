from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from sci_etl_core.embeddings.openai_compatible_async import AsyncOpenAIEmbedder
from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.llm.openai_compatible_async import AsyncOpenAICompatibleClient
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser
from sci_etl_core.rate_limiter import (
    AsyncRateLimiter,
    HostRateLimiter,
    NullRateLimiter,
    SemaphoreRateLimiter,
    limiter_for,
)


class RecordingLimiter(AsyncRateLimiter):
    def __init__(self, name: str = "limiter", journal: list[str] | None = None) -> None:
        self.name = name
        self.journal = journal if journal is not None else []
        self.inside = 0

    async def __aenter__(self) -> "RecordingLimiter":
        self.inside += 1
        self.journal.append(f"{self.name}:enter")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.inside -= 1
        self.journal.append(f"{self.name}:exit")


class TestHostRateLimiter:
    def test_matches_the_exact_host(self):
        api = RecordingLimiter()
        assert HostRateLimiter({"export.arxiv.org": api}).for_url("https://export.arxiv.org/api/query") is api

    def test_a_parent_domain_covers_its_subdomains(self):
        arxiv = RecordingLimiter()
        hosts = HostRateLimiter({"arxiv.org": arxiv})
        assert hosts.for_url("https://export.arxiv.org/api/query") is arxiv
        assert hosts.for_url("https://arxiv.org/pdf/1.pdf") is arxiv

    def test_the_most_specific_host_wins(self):
        api, site = RecordingLimiter(), RecordingLimiter()
        hosts = HostRateLimiter({"arxiv.org": site, "export.arxiv.org": api})
        assert hosts.for_url("https://export.arxiv.org/api/query") is api
        assert hosts.for_url("https://arxiv.org/e-print/1") is site

    def test_a_suffix_that_is_not_a_whole_label_does_not_match(self):
        hosts = HostRateLimiter({"arxiv.org": RecordingLimiter()})
        assert isinstance(hosts.for_url("https://notarxiv.org/x"), NullRateLimiter)

    def test_matching_ignores_case_ports_and_surrounding_dots(self):
        limiter = RecordingLimiter()
        hosts = HostRateLimiter({" .API.Example.COM. ": limiter})
        assert hosts.for_url("https://api.example.com.:8443/v1") is limiter

    def test_unmatched_hosts_use_the_default(self):
        default = RecordingLimiter()
        hosts = HostRateLimiter({"arxiv.org": RecordingLimiter()}, default=default)
        assert hosts.for_url("https://api.openai.com/v1") is default
        assert hosts.for_url("not a url") is default

    def test_rejects_a_blank_host(self):
        with pytest.raises(ValueError, match="must not be blank"):
            HostRateLimiter({" . ": RecordingLimiter()})

    def test_rejects_a_host_configured_twice(self):
        with pytest.raises(ValueError, match="configured more than once"):
            HostRateLimiter({"arxiv.org": RecordingLimiter(), "ArXiv.org.": RecordingLimiter()})


class TestLimiterFor:
    def test_none_is_unlimited(self):
        assert isinstance(limiter_for(None, "https://x"), NullRateLimiter)

    def test_a_plain_limiter_applies_to_every_url(self):
        limiter = RecordingLimiter()
        assert limiter_for(limiter, "https://a") is limiter
        assert limiter_for(limiter, "https://b") is limiter

    def test_a_host_limiter_is_resolved_by_url(self):
        limiter = RecordingLimiter()
        assert limiter_for(HostRateLimiter({"a.org": limiter}), "https://a.org/x") is limiter


def _arxiv(client, mocker, **kwargs):
    latex = mocker.Mock(spec=LatexTarballParser)
    latex.extract_text.return_value = "latex body"
    return AsyncArxivExtractor(
        client=client,
        pdf_parser=mocker.Mock(spec=PdfPlumberParser),
        latex_parser=latex,
        sleep=mocker.AsyncMock(),
        **kwargs,
    )


def _http_response(status: int, content: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(status_code=status, content=content, headers={})


class TestArxivExtractorRateLimiting:
    @pytest.mark.asyncio
    async def test_every_attempt_takes_a_slot_that_is_free_during_the_retry_wait(self, mocker):
        journal: list[str] = []
        limiter = RecordingLimiter(journal=journal)
        client = mocker.Mock()

        async def get(*_args, **_kwargs):
            journal.append("get")
            assert limiter.inside == 1
            return _http_response(503) if journal.count("get") == 1 else _http_response(200, b"<feed/>")

        async def sleep(_delay):
            journal.append("sleep")
            assert limiter.inside == 0

        client.get = get
        extractor = _arxiv(client, mocker, rate_limiter=limiter)
        extractor._sleep = sleep
        assert await extractor.search("q", 10, 0) == b"<feed/>"
        attempt = ["limiter:enter", "get", "limiter:exit"]
        assert journal == ["sleep", *attempt, "sleep", *attempt]

    @pytest.mark.asyncio
    async def test_a_host_limiter_budgets_the_api_and_the_full_text_hosts_apart(self, mocker):
        journal: list[str] = []
        api = RecordingLimiter("api", journal)
        site = RecordingLimiter("site", journal)
        client = mocker.Mock()
        client.get = mocker.AsyncMock(return_value=_http_response(200, b"payload"))
        extractor = _arxiv(client, mocker, rate_limiter=HostRateLimiter({"export.arxiv.org": api, "arxiv.org": site}))
        await extractor.search("q", 10, 0)
        await extractor.fetch_full_text(RawRecord("2401.00001v1", "t", "a"))
        assert journal == ["api:enter", "api:exit", "site:enter", "site:exit"]

    @pytest.mark.asyncio
    async def test_a_transport_error_still_releases_the_slot(self, mocker):
        limiter = RecordingLimiter()
        client = mocker.Mock()
        client.get = mocker.AsyncMock(side_effect=httpx.ConnectError("down"))
        extractor = _arxiv(client, mocker, rate_limiter=limiter, max_retries=2)
        with pytest.raises(Exception, match="failed after 2 attempts"):
            await extractor.search("q", 10, 0)
        assert limiter.inside == 0
        assert limiter.journal.count("limiter:enter") == 2

    @pytest.mark.asyncio
    async def test_one_limiter_caps_concurrency_across_extractors(self, mocker):
        shared = SemaphoreRateLimiter(max_concurrency=1)
        active = peak = 0

        async def get(*_args, **_kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return _http_response(200, b"ok")

        clients = [mocker.Mock(), mocker.Mock()]
        for client in clients:
            client.get = get
        extractors = [_arxiv(client, mocker, rate_limiter=shared) for client in clients]
        await asyncio.gather(*(extractor.search("q", 1, 0) for extractor in extractors for _ in range(3)))
        assert peak == 1


class TestOpenAIClientsRateLimiting:
    @pytest.mark.asyncio
    async def test_chat_client_enters_the_limiter_matching_its_base_url(self, mocker):
        openai = mocker.patch("sci_etl_core.llm.openai_compatible_async.AsyncOpenAI").return_value
        provider = RecordingLimiter()

        async def create(**_kwargs):
            assert provider.inside == 1
            message = SimpleNamespace(content='{"ok": true}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

        openai.chat.completions.create = create
        client = AsyncOpenAICompatibleClient(
            api_key="k",
            base_url="https://api.provider.com/v1",
            model="m",
            rate_limiter=HostRateLimiter({"provider.com": provider}),
        )
        assert await client.complete_json("s", "u") == {"ok": True}
        assert provider.journal == ["limiter:enter", "limiter:exit"]

    @pytest.mark.asyncio
    async def test_embedder_takes_a_slot_per_batch_and_per_retry(self, mocker):
        limiter = RecordingLimiter()
        embedder = AsyncOpenAIEmbedder(
            api_key="k",
            base_url="https://x/v1",
            model="e",
            batch_size=1,
            sleep=mocker.AsyncMock(),
            rate_limiter=limiter,
        )
        timeout = httpx.Request("POST", "https://x/v1/embeddings")
        responses = [
            APITimeoutError(request=timeout),
            SimpleNamespace(data=[SimpleNamespace(embedding=[1.0])], usage=None),
            SimpleNamespace(data=[SimpleNamespace(embedding=[2.0])], usage=None),
        ]
        client = mocker.Mock()
        client.embeddings.create = mocker.AsyncMock(side_effect=responses)
        embedder._client = client
        assert await embedder.embed(["a", "b"]) == [[1.0], [2.0]]
        assert limiter.journal.count("limiter:enter") == 3
        assert limiter.inside == 0
