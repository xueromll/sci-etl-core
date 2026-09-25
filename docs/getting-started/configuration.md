# Configuration

Settings load from a YAML file and a `.env` file into Pydantic models:

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

| Section | Model | Fields (defaults) | Builds |
|---------|-------|-------------------|--------|
| `llm` | `LLMConfig` | `api_key`, `base_url` (`https://api.openai.com/v1`), `model` (`gpt-4o-mini`), `timeout` (120) | `AsyncOpenAICompatibleClient.from_config` |
| `http` | `HttpConfig` | `user_agent` (`sci-etl-core/<installed version>`), `max_retries` (3), `backoff_factor` (2.0), `timeout` (25) | `build_client()`, `AsyncArxivExtractor.from_config` |
| `full_text` | `RateLimitConfig` | `max_concurrency` (4), `max_rate` (unset), `time_period` (1.0) | `build_limiter()` |
| `pipeline` | `PipelineConfig` | `search_query` (`""`), `total_limit` (100), `page_size` (100), `search_delay` (3.0), `sleep_between` (5.0), `max_concurrency` (6), `newest_first` (false) | `AsyncETLPipeline.from_config`, `run_arguments()`, `AsyncArxivExtractor.from_config` |
| `search` | `SearchConfig` | `bm25`, `fusion`, `hybrid`, `graph`, with the defaults of the dataclasses they build | `bm25.to_weights()`, `fusion.to_params()`, `hybrid.to_params()`, `graph.to_params()` |

## Building components from the config

Each section builds, or is passed to, the components it configures. Values you
pass yourself override the config:

```python
from sci_etl_core import AsyncArxivExtractor, AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

extractor = AsyncArxivExtractor.from_config(
    config.http,
    config.pipeline,
    client=config.http.build_client(),
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    rate_limiter=config.full_text.build_limiter(),
)
llm = AsyncOpenAICompatibleClient.from_config(config.llm)
pipeline = AsyncETLPipeline.from_config(
    config.pipeline,
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
    destination="results.csv",
)
await pipeline.run(**config.pipeline.run_arguments())
```

`AsyncArxivExtractor.from_config` takes `max_retries` and `backoff_factor`
from `http` and `search_delay` from `pipeline`. `AsyncOpenAICompatibleClient`
takes `api_key` (the loaded `SecretStr` as-is), `base_url`, `model`, and
`timeout` as `default_timeout`. Both accept any other constructor argument,
such as `logger` or `rate_limiter`, as a keyword. The PubMed, Semantic
Scholar, and OpenAlex extractors have no `from_config`; pass
`config.http.max_retries` and `config.http.backoff_factor` to their
constructors yourself. The pipeline takes `max_concurrency`, and `run_arguments()` returns
`query`, `page_size`, `total_limit`, `sleep_between`, and `newest_first` for
`run()`; add `max_attempts` or `start_index` yourself when you need them. `ETLPipeline.from_config` works the same way.

The search section builds the parameter dataclasses for
[local search](../guide/search/index.md):

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

## Strict sections

Every section the library defines rejects a key it does not declare, so a typo
fails loudly instead of being ignored. The `ConfigurationError` names the key:

```text
Invalid configuration in config.yaml:
  search.bm25.titel: Extra inputs are not permitted
```

The keys `pipeline.max_records` and `pipeline.max_workers`, renamed in 0.4, are rejected
the same way since 0.5; use `total_limit` and `max_concurrency`. An application
that must still load a file with unknown keys in the library's sections sets
`strict_sections = False` on its config class. Each unknown key is then
dropped with a `UserWarning` that names it:

```python
from sci_etl_core import BaseAppConfig


class MyConfig(BaseAppConfig):
    strict_sections = False
```

Top-level sections your application adds are kept either way, and a section
type you define yourself validates as its own `model_config` says.

## Details

- **API key.** The key comes from the `LLM_API_KEY` environment variable
  (choose another with `api_key_env_var=`), which can be loaded from a `.env`
  file: the one you pass, or else the first `.env` found from the current
  working directory upward. It is stored as a Pydantic `SecretStr`, so it doesn't
  show up in reprs or logs. Variables already set in the environment take
  precedence over `.env`; copy `.env.example` to get started.
- **The environment wins over YAML.** When the variable is set, it overrides
  any `llm.api_key` in the YAML file, which is used only as a fallback. Keep
  keys out of config files anyway.
- **Project-specific settings.** `BaseAppConfig` accepts extra top-level keys,
  or you can subclass it. Keys inside the library's own sections must be ones
  those sections declare; see [Strict sections](#strict-sections).
- **Async loading.** `load_config_async` takes the same arguments.
- **Errors.** A missing or unparseable YAML file, a file whose top level isn't
  a mapping, and a validation failure all raise `ConfigurationError`.
  Validation checks ranges too: counts such as `max_concurrency`, `page_size`,
  and `max_retries` must be at least 1, timeouts and `time_period` must be
  positive, delays and `total_limit` must not be negative, BM25 weights must
  be finite and not negative, and `graph.min_weight` must be finite.
  `fusion.weights` is checked only when `fusion.to_params()` builds
  the parameters, which raises `ValueError` for a negative or non-finite
  weight. A validation message lists each failing key and the reason
  on its own line but never the value, so an API key can't reach a log through
  it. `validate_config(config_cls, raw, source)` applies the same checks to
  settings loaded some other way.
