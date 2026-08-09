# Migration Guide

This guide helps you migrate a project onto `sci-etl-core`. It uses
`udg-catalogue` — the astronomy pipeline the library was extracted from — as the
worked example, but every step is domain-agnostic.

## Why Migrate

`sci-etl-core` extracts the reusable ETL machinery out of individual research
projects so you no longer maintain a bespoke pipeline per corpus. Migrating buys
you:

- **One async core, two calling styles.** Implementations are written once as
  `async` and exposed through a generated sync facade — no more parallel,
  drifting sync/async copies.
- **Injectable components.** Sources, models, and destinations are constructor
  arguments, not hard-coded module globals.
- **Typed config and secrets.** YAML + `.env` validated by Pydantic, with API
  keys held as `SecretStr`.
- **Shared, tested primitives.** Rate limiting, retrying HTTP, reference
  trimming, dedup, and state tracking are maintained and covered once.

## Breaking Changes

Moving from an in-repo pipeline (e.g. `udg-catalogue`) to `sci-etl-core`:

| Area | Before (`udg-catalogue`) | After (`sci-etl-core`) |
|------|--------------------------|------------------------|
| Package layout | flat modules in the project | `sci_etl_core.*` namespaced imports |
| Sync vs async | hand-maintained duplicate modules | async core + generated sync facade |
| Sources | arXiv logic hard-coded in the pipeline | inject an `Extractor` / `AsyncExtractor` |
| LLM calls | inline OpenAI calls | inject an `LLMClient` implementation |
| Secrets | plain strings / raw env reads | Pydantic `SecretStr` via `load_config` |
| Config | ad-hoc parsing | `BaseAppConfig` + `load_config[_async]` |
| Logging | per-module setup | `configure_logging(name, log_file)` |
| Record shape | project-specific dict/objects | `RawRecord` dataclass |
| Rate limiting | manual `asyncio.Semaphore` | `build_rate_limiter(...)` abstraction |
| State | bespoke JSON/txt handling | `FileStateManager` / `AsyncFileStateManager` |

**Behavioral notes**

- The sync facade runs the async core on a private background event loop. Do not
  call sync classes from inside a running `asyncio` loop; use the `Async*`
  classes there instead.
- `ETLPipeline.run(...)` accepts `total_limit` / `page_size`; the legacy single
  `max_records` value is still honored as a backward-compatible alias that seeds
  both.
- `RawRecord` requires `record_id`, `title`, and `abstract`; map your prior
  fields onto these plus the free-form `metadata` dict.

## Step-by-Step Migration

### 1. Install

```bash
pip install "sci-etl-core[async,llm,viz]"
```

### 2. Replace hard-coded source logic with an injected extractor

Before — arXiv querying lived inside the pipeline:

```python
# udg-catalogue/pipeline.py (old)
def search_arxiv(query, start):
    resp = requests.get(ARXIV_URL, params={...})
    return parse_feed(resp.content)
```

After — inject a concrete `Extractor`; the pipeline never knows it's arXiv:

```python
from sci_etl_core import AsyncArxivExtractor
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import PdfPlumberParser, LatexTarballParser

extractor = AsyncArxivExtractor(
    client=build_async_client(),
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
)
```

### 3. Move configuration to YAML + `.env`

```yaml
# config.yaml
llm:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
pipeline:
  search_query: "all:galaxy"
  max_records: 200
full_text:
  max_concurrency: 4
```

```bash
# .env  (never commit this)
LLM_API_KEY=sk-...
```

```python
from pathlib import Path
from sci_etl_core.config import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
```

Need project-specific settings? `BaseAppConfig` allows extra fields, or subclass
it:

```python
from sci_etl_core.config import BaseAppConfig

class CatalogueConfig(BaseAppConfig):
    magnitude_limit: float = 24.0
```

### 4. Wrap the LLM steps

```python
from sci_etl_core import (
    AsyncOpenAICompatibleClient,
    AsyncLLMRelevanceFilter,
    AsyncLLMEntityExtractor,
)

llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,          # SecretStr is accepted directly
    base_url=config.llm.base_url,
    model=config.llm.model,
)
relevance = AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT)
entities = AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT)
```

### 5. Assemble the pipeline

```python
from sci_etl_core import (
    AsyncCsvUpsertExporter,
    AsyncFileStateManager,
    AsyncETLPipeline,
)
from sci_etl_core.processors import DefaultKeyNormalizer

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance,
    entity_extractor=entities,
    exporter=AsyncCsvUpsertExporter(
        key_column="record_id",
        value_columns=["magnitude", "redshift"],
        normalizer=DefaultKeyNormalizer(),
    ),
    state_manager=AsyncFileStateManager("processed.txt", "state.json"),
    destination="catalogue.csv",
    max_concurrency=config.full_text.max_concurrency,
)

async with pipeline:
    await pipeline.run(query=config.pipeline.search_query,
                       total_limit=config.pipeline.max_records)
```

### 6. Point post-processing at the shared processors

```python
from sci_etl_core.processors import ProcessorChain, NormalizationStep, DeduplicationStep

chain = ProcessorChain([NormalizationStep(...), DeduplicationStep(...)])
clean = chain.process(dataframe)
```

### 7. Delete the old duplicated code

Once the injected components produce identical output, remove the project's
bespoke HTTP session, retry logic, semaphore juggling, and sync/async copies.

## Verifying the Migration

- Run against a small `total_limit` and diff the output CSV against a
  pre-migration run.
- Keep your prompts and normalizer identical first; change behavior only after
  parity is confirmed.
- Run `pytest` — the offline suite catches interface mismatches early.

Questions or a rough edge in your migration? Open a
[discussion or issue](.github/ISSUE_TEMPLATE/bug_report.md) — we're happy to help.
