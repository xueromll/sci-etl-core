# Configuration

Settings load from a YAML file and a `.env` file into Pydantic models:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
print(config.llm.model, config.pipeline.max_records)
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
  max_records: 100
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_workers: 6
```

| Section | Model | Fields (defaults) | Pass to |
|---------|-------|-------------------|---------|
| `llm` | `LLMConfig` | `api_key`, `base_url` (`https://api.openai.com/v1`), `model` (`gpt-4o-mini`), `timeout` (120) | `AsyncOpenAICompatibleClient` |
| `http` | `HttpConfig` | `user_agent` (`sci-etl-core/0.1`), `max_retries` (3), `backoff_factor` (2.0), `timeout` (25) | `build_async_client`, `AsyncArxivExtractor` |
| `full_text` | `RateLimitConfig` | `max_concurrency` (4), `max_rate` (unset), `time_period` (1.0) | `build_rate_limiter` |
| `pipeline` | `PipelineConfig` | `search_query` (`""`), `max_records` (100), `page_size` (100), `search_delay` (3.0), `sleep_between` (5.0), `max_workers` (6) | `AsyncETLPipeline`, `AsyncArxivExtractor`, `run()` |

## Passing settings to components

**Components don't read the config on their own** — copy the values into the
constructors:

```python
from sci_etl_core import AsyncArxivExtractor, AsyncOpenAICompatibleClient
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

client = build_async_client(timeout=config.http.timeout, user_agent=config.http.user_agent)
extractor = AsyncArxivExtractor(
    client=client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    max_retries=config.http.max_retries,
    backoff_factor=config.http.backoff_factor,
    sleep_before_search=config.pipeline.search_delay,
)
llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    default_timeout=config.llm.timeout,
)
```

`api_key` accepts the loaded `SecretStr` as-is. The pipeline settings go to the
pipeline and its `run` call:

```python
pipeline = AsyncETLPipeline(..., max_concurrency=config.pipeline.max_workers)
await pipeline.run(
    query=config.pipeline.search_query,
    page_size=config.pipeline.page_size,
    total_limit=config.pipeline.max_records,
    sleep_between=config.pipeline.sleep_between,
)
```

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
  or you can subclass it.
- **Async loading.** `load_config_async` takes the same arguments.
- **Errors.** A missing or unparseable YAML file, a file whose top level isn't
  a mapping, and a validation failure all raise `ConfigurationError`.
  Validation checks ranges too: counts such as `max_workers`, `page_size`,
  `max_retries`, and `max_concurrency` must be at least 1, timeouts and
  `time_period` must be positive, and delays and `max_records` must not be
  negative. A validation message lists each failing key and the reason on its
  own line but never the value, so an API key can't reach a log through it.
  `validate_config(config_cls, raw, source)` applies the same checks to
  settings loaded some other way.
