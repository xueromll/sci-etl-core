# 配置

设置从 YAML 文件（以及可选的 `.env` 文件）加载到 Pydantic 模型中。加载需要 `config`
extra：

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
print(config.llm.model, config.pipeline.total_limit)
```

```yaml title="config.yaml"
llm:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  timeout: 120
http:
  user_agent: "my-project/1.0 (mailto:you@example.org)"
  max_retries: 3
  timeout: 25
full_text:
  max_concurrency: 4
pipeline:
  search_query: "all:galaxy"
  total_limit: 100
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_concurrency: 6
  newest_first: true
search:
  bm25: {title: 10, abstract: 4, body: 1}
  fusion: {k: 60}
  hybrid: {candidate_pool: 100, chunk_pool_factor: 5}
  graph: {depth: 2, fanout: 8, min_weight: 0.35}
```

| 部分 | 模型 | 字段（默认值） | 构建 |
|------|------|----------------|------|
| `llm` | `LLMConfig` | `api_key`、`base_url`（`https://api.openai.com/v1`）、`model`（`gpt-4o-mini`）、`timeout`（120）、`structured_output`（false） | `AsyncOpenAICompatibleClient.from_config` |
| `http` | `HttpConfig` | `user_agent`（`sci-etl-core/<installed version>`）、`max_retries`（3）、`backoff_factor`（2.0）、`timeout`（25） | `build_client()`、`AsyncArxivExtractor.from_config` |
| `full_text` | `RateLimitConfig` | `max_concurrency`（4）、`max_rate`（未设置）、`time_period`（1.0） | `build_limiter()`、`AsyncArxivExtractor.from_config` |
| `pipeline` | `PipelineConfig` | `search_query`（`""`）、`total_limit`（100）、`page_size`（100）、`search_delay`（3.0）、`sleep_between`（5.0）、`max_concurrency`（6）、`newest_first`（false） | `AsyncETLPipeline.from_config`、`run_arguments()`、`AsyncArxivExtractor.from_config` |
| `search` | `SearchConfig` | `bm25`、`fusion`、`hybrid`、`graph`，默认值与它们所构建的 dataclass 相同 | `bm25.to_weights()`、`fusion.to_params()`、`hybrid.to_params()`、`graph.to_params()` |

## 根据配置构建组件 {#building-components-from-the-config}

每个部分都会构建它所配置的组件，或被传给这些组件。你自己传入的值优先于配置：

```python
from sci_etl_core import AsyncArxivExtractor, AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

extractor = AsyncArxivExtractor.from_config(
    config.http,
    config.pipeline,
    client=config.http.build_client(),
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    full_text=config.full_text,
)
llm = AsyncOpenAICompatibleClient.from_config(config.llm)
pipeline = AsyncETLPipeline.from_config(
    config.pipeline,
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
)
await pipeline.run(**config.pipeline.run_arguments())
```

`AsyncArxivExtractor.from_config` 从 `http` 读取 `max_retries` 和 `backoff_factor`，从
`pipeline` 读取 `search_delay`，从 `full_text` 获得它的 `rate_limiter`。省略 `full_text`
时，提取器没有速率限制器，因此 `max_concurrency` 为 6 的流水线会同时从 arxiv.org 下载六篇
论文。`AsyncOpenAICompatibleClient` 读取 `api_key`（按原样使用加载得到的 `SecretStr`）、
`base_url`、`model`、`structured_output`，并把 `timeout` 用作 `default_timeout`。只有当
端点接受 `json_schema` 响应格式时（例如 OpenAI 的端点）才设置 `structured_output: true`；
DeepSeek 的端点不接受。两者都可以通过关键字接受任何其他构造参数，例如 `rate_limiter`。
PubMed、Semantic Scholar 和 OpenAlex 提取器没有 `from_config`；请自行把
`config.http.max_retries` 和 `config.http.backoff_factor` 传给它们的构造函数。流水线读取
`max_concurrency`，`run_arguments()` 为 `run()` 返回 `query`、`page_size`、`total_limit`、
`sleep_between` 和 `newest_first`；需要 `max_attempts` 或 `start_index` 时请自行添加。
`ETLPipeline.from_config` 的用法相同。

search 部分为[本地检索](../guide/search/index.md)构建参数 dataclass：

```python
from sci_etl_core.search import AsyncHybridSearcher, AsyncSqliteFts5Store

store = AsyncSqliteFts5Store("search.db", weights=config.search.bm25.to_weights())
searcher = AsyncHybridSearcher(
    store,
    finder,
    fusion=config.search.fusion.to_params(),
    params=config.search.hybrid.to_params(),
)
```

## 严格的配置部分 {#strict-sections}

本库定义的每个部分都会拒绝它未声明的键，因此拼写错误会明确报错，而不是被忽略。
`ConfigurationError` 会指明该键：

```text
Invalid configuration in config.yaml:
  search.bm25.titel: Extra inputs are not permitted
```

在 0.4 中改名的键 `pipeline.max_records` 和 `pipeline.max_workers` 自 0.5 起也会以同样
方式被拒绝；请使用 `total_limit` 和 `max_concurrency`。如果应用程序仍需加载在本库的部分中
含有未知键的文件，可在其配置类上设置 `strict_sections = False`。此时每个未知键都会被丢弃，
并发出一条指明该键的 `UserWarning`：

```python
from sci_etl_core import BaseAppConfig


class MyConfig(BaseAppConfig):
    strict_sections = False
```

无论哪种情况，应用程序添加的顶层部分都会保留；你自己定义的部分类型则按其自身的
`model_config` 进行校验。

## 细节 {#details}

- **API 密钥。** 密钥来自 `LLM_API_KEY` 环境变量（可用 `api_key_env_var=` 换成其他变量）。
  只有在你要求时才会把 `.env` 文件读入环境：把它的路径作为 `env_path` 传入，或者传入
  `load_env=True`，以使用从当前工作目录向上找到的第一个 `.env`。两者都不传时，
  `load_config` 永远不会读取 `.env` 文件，因此导入和配置本库不会改变任何环境变量。密钥以
  Pydantic `SecretStr` 存储，因此不会出现在 repr 或日志中。环境中已设置的变量优先于
  `.env`；可以复制 `.env.example` 作为起点。
- **环境变量优先于 YAML。** 设置了该变量时，它会覆盖 YAML 文件中的任何 `llm.api_key`，后者
  只作为后备。无论如何，都不要把密钥写进配置文件。
- **项目专属设置。** `BaseAppConfig` 接受额外的顶层键，你也可以继承它。本库自身各部分中的
  键必须是这些部分声明过的；参见[严格的配置部分](#strict-sections)。
- **异步加载。** `load_config_async` 接受相同的参数。
- **错误。** YAML 文件缺失或无法解析、文件顶层不是映射，以及校验失败，都会抛出
  `ConfigurationError`。校验也会检查取值范围：`max_concurrency`、`page_size`、
  `max_retries` 等计数必须至少为 1，超时和 `time_period` 必须为正，延迟和 `total_limit`
  不能为负，BM25 权重必须有限且非负，`graph.min_weight` 必须有限。`fusion.weights` 只在
  `fusion.to_params()` 构建参数时检查，遇到负数或非有限的权重会抛出 `ValueError`。校验消息
  会在单独的行中列出每个出错的键及原因，但从不包含值，因此 API 密钥不会经由它进入日志。
  `validate_config(config_cls, raw, source)` 对以其他方式加载的设置执行相同的检查。
