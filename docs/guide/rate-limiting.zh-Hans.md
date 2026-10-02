# 速率限制

`AsyncETLPipeline(max_concurrency=...)` 限制同时处理的记录数。如需更精细的控制，
`sci_etl_core.rate_limiter` 提供了异步限制器：

- `SemaphoreRateLimiter`：并发上限
- `AioLimiterRateLimiter`：令牌桶；需要 `async` extra
- `NullRateLimiter`：不限制

`build_rate_limiter(max_concurrency, max_rate, time_period)` 在设置了 `max_rate` 时返回
令牌桶，否则返回信号量。它的参数与 `full_text` [配置部分](../getting-started/configuration.md)
一致。

## 为组件提供限制器 {#giving-a-limiter-to-a-component}

每个内置提取器（`AsyncArxivExtractor`、`AsyncPubMedExtractor`、
`AsyncSemanticScholarExtractor` 和 `AsyncOpenAlexExtractor`）、
`AsyncOpenAICompatibleClient` 和 `AsyncOpenAIEmbedder` 都接受 `rate_limiter`。
每个 HTTP 请求（包括重试）都会先等待一个空位，并在响应到达时归还，因此组件在等待重试时
不会占用任何空位：

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

## 按主机限制 {#limits-per-host}

`HostRateLimiter` 根据请求所访问的主机选择限制器。一个主机也涵盖其子域名，除非某个子域名
有自己的限制器；没有匹配的主机使用 `default`，省略它时即为不限制。arXiv 提取器会访问两个
主机：用于列表的 `export.arxiv.org` 和用于全文的 `arxiv.org`，因此可以为二者分别设置配额：

```python
from sci_etl_core.rate_limiter import HostRateLimiter, SemaphoreRateLimiter, build_rate_limiter

arxiv_limits = HostRateLimiter(
    {
        "export.arxiv.org": build_rate_limiter(max_rate=1, time_period=3.0),
        "arxiv.org": SemaphoreRateLimiter(max_concurrency=4),
    }
)
```

## 在组件之间共享限制 {#sharing-a-limit-between-components}

把同一个限制器传给多个组件，它们就会共享同一份配额。调用同一服务商的聊天客户端和嵌入器
会消耗同一份额度：

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

`HostRateLimiter` 也可以用同样的方式共享，例如用一个实例覆盖一次运行所调用的所有服务的
主机。OpenAI 兼容客户端会用它们的 `base_url` 进行匹配。
