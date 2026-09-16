# Rate limiting

`AsyncETLPipeline(max_concurrency=...)` bounds how many records are processed
at once. For finer control, `sci_etl_core.rate_limiter` provides async
limiters:

- `SemaphoreRateLimiter` — concurrency cap
- `AioLimiterRateLimiter` — token bucket; needs the `async` extra
- `NullRateLimiter` — no limit

`build_rate_limiter(max_concurrency, max_rate, time_period)` returns a token
bucket when `max_rate` is set and a semaphore otherwise. Its parameters match
the `full_text` [config section](../getting-started/configuration.md).

## Giving a limiter to a component

Every bundled extractor (`AsyncArxivExtractor`, `AsyncPubMedExtractor`,
`AsyncSemanticScholarExtractor`, and `AsyncOpenAlexExtractor`),
`AsyncOpenAICompatibleClient`, and `AsyncOpenAIEmbedder` take a
`rate_limiter`. Every HTTP request, retries included, waits for a slot
first and gives it back when the response arrives, so no slot is held while a
component waits to retry:

```python
from sci_etl_core import AsyncArxivExtractor
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncArxivExtractor(
    client=client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    rate_limiter=build_rate_limiter(max_rate=1, time_period=3.0),
)
```

## Limits per host

`HostRateLimiter` picks a limiter by the host a request goes to. A host also
covers its subdomains, unless a subdomain has a limiter of its own, and hosts
with no match use `default`, which is no limit when you leave it out. The arXiv
extractor calls two hosts, `export.arxiv.org` for listings and `arxiv.org` for
full text, so each can get its own budget:

```python
from sci_etl_core.rate_limiter import HostRateLimiter, SemaphoreRateLimiter, build_rate_limiter

arxiv_limits = HostRateLimiter(
    {
        "export.arxiv.org": build_rate_limiter(max_rate=1, time_period=3.0),
        "arxiv.org": SemaphoreRateLimiter(max_concurrency=4),
    }
)
```

## Sharing a limit between components

Pass the same limiter to several components to have them share one budget. A
chat client and an embedder that call the same provider count against the same
quota:

```python
from sci_etl_core import AsyncOpenAICompatibleClient, AsyncOpenAIEmbedder
from sci_etl_core.rate_limiter import build_rate_limiter

provider_limit = build_rate_limiter(max_rate=50, time_period=60.0)
llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    rate_limiter=provider_limit,
)
embedder = AsyncOpenAIEmbedder(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model="text-embedding-3-small",
    rate_limiter=provider_limit,
)
```

A `HostRateLimiter` can be shared the same way, for example one instance whose
hosts cover every service a run calls. The OpenAI-compatible clients match it
against their `base_url`.
