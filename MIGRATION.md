# Migrating a Project to sci-etl-core

This guide walks through replacing a pipeline that lives inside a research
project with `sci-etl-core` components. It uses `udg-catalogue`, the astronomy
pipeline the library was extracted from, as the worked example, but every step
is domain-agnostic.

---

## Why migrate

`sci-etl-core` moves the reusable ETL machinery out of individual research
projects, so you no longer maintain a bespoke pipeline for each corpus:

- **One async implementation per component.** No parallel sync/async copies to
  keep in step; blocking scripts use `ETLPipeline`.
- **Injectable components.** Sources, models, prompts, and destinations are
  constructor arguments, not hard-coded module globals.
- **Typed config and secrets.** YAML + `.env` validated by Pydantic, with API
  keys held as `SecretStr`.
- **Shared, tested primitives.** Retrying arXiv access, reference trimming,
  crash-safe CSV upserts, resumable state, deduplication, and optional semantic
  memory are maintained and tested in one place.

## What changes

| Area | Before (`udg-catalogue`) | After (`sci-etl-core`) |
|------|--------------------------|------------------------|
| Package layout | flat modules in the project | `sci_etl_core.*` namespaced imports |
| Sync vs async | hand-maintained duplicate modules | async components; `ETLPipeline` for blocking scripts |
| Sources | arXiv logic hard-coded in the pipeline | inject an `AsyncExtractor` |
| LLM calls | inline OpenAI calls | inject an `AsyncLLMClient` into `AsyncLLMRelevanceFilter` / `AsyncLLMEntityExtractor` |
| Secrets | plain strings / raw env reads | `SecretStr` via `load_config` |
| Config | ad-hoc parsing | `BaseAppConfig` + `load_config` / `load_config_async` |
| Logging | per-module setup | `configure_logging(name, log_file)`, passed as `logger=log.info` |
| Record shape | project-specific dicts/objects | `RawRecord(record_id, title, abstract, source_url=None, metadata={})` |
| Concurrency | manual `asyncio.Semaphore` | `AsyncETLPipeline(max_concurrency=...)`; extra limits via `sci_etl_core.rate_limiter` |
| State | bespoke JSON/txt handling | `AsyncFileStateManager` or `AsyncSqliteStateManager` |
| Failures | silent stops / bare exceptions | `PipelineAborted` and the `SciEtlError` hierarchy |

## Steps

### 1. Install

```bash
pip install "sci-etl-core[async,llm,pdf]"
```

These extras cover the arXiv extractor, the OpenAI-compatible client, PDF
parsing, and CSV export. Add others as you opt in to more components; see
[Installation](README.md#installation).

### 2. Replace hard-coded source logic with an injected extractor

Before, arXiv querying lived inside the pipeline:

```python
# udg-catalogue/pipeline.py (old)
def search_arxiv(query, start):
    resp = requests.get(ARXIV_URL, params={...})
    return parse_feed(resp.content)
```

After, you inject a concrete `AsyncExtractor`, and the pipeline never knows
the source is arXiv:

```python
from sci_etl_core import AsyncArxivExtractor
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

client = build_async_client()
extractor = AsyncArxivExtractor(
    client=client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
)
```

For a source other than arXiv, implement the `AsyncExtractor` contract
described in [Supported Sources](README.md#supported-sources).

### 3. Move configuration to YAML + `.env`

```yaml
# config.yaml
llm:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
pipeline:
  search_query: "all:galaxy"
  max_records: 200
  max_workers: 4
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

For project-specific settings, subclass `BaseAppConfig` (it also accepts extra
keys):

```python
from sci_etl_core.config import BaseAppConfig


class CatalogueConfig(BaseAppConfig):
    magnitude_limit: float = 24.0
```

Config values aren't applied automatically. Pass them to constructors and to
`run()`, as the steps below do.

### 4. Wrap the LLM steps

```python
from sci_etl_core import (
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
)

RELEVANCE_PROMPT = (
    "Decide whether the paper studies ultra-diffuse galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "List every galaxy with a measured magnitude or redshift. Reply with JSON: "
    '{"items": [{"name": "...", "magnitude": 0.0, "redshift": 0.0}]}.'
)

llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,  # SecretStr is accepted directly
    base_url=config.llm.base_url,
    model=config.llm.model,
)
relevance = AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT)
entities = AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT)
```

Keep your existing prompts, but make sure each one mentions **JSON** (JSON mode
requires it) and asks for these response shapes:

- relevance: `{"relevant": true}` or `{"relevant": false}`
- extraction: `{"items": [{...}, ...]}`, where each item is an object that
  includes the field you'll use as the CSV key

The two steps handle failure differently:

- **Relevance.** When the LLM call fails, or the reply has no clear verdict,
  `AsyncLLMRelevanceFilter` lets the record through. Pass
  `default_on_error=False` to drop such records instead.
- **Extraction.** When the LLM call fails, or the reply isn't a list of
  objects, `AsyncLLMEntityExtractor` raises `LLMError`. The pipeline logs it,
  leaves the record unmarked, and retries it on the next run.

### 5. Choose a state backend and bring over existing progress

- `AsyncFileStateManager("state/processed.txt", "state/metadata.json")` keeps
  one processed id per line, plus `{"last_run_date": ..., "last_start_index": N}`.
- `AsyncSqliteStateManager("state/pipeline.db")` stores the same data in
  SQLite.

To carry over ids your old pipeline already processed, load them once before
the first run:

```python
from sci_etl_core import PipelineMetadata
from sci_etl_core.state import AsyncSqliteStateManager


async def import_legacy_state(ids: list[str], last_start_index: int) -> None:
    state = AsyncSqliteStateManager("state/pipeline.db")
    for record_id in ids:
        await state.mark_processed(record_id)
    await state.save_metadata(PipelineMetadata(last_start_index=last_start_index))
    await state.aclose()
```

**Imported ids must match the ids your extractor produces**, or every record
is processed again. `AsyncArxivExtractor` uses the bare arXiv id with its
version suffix, such as `2401.00001v1`: convert ids your old pipeline stored as
URLs (`http://arxiv.org/abs/2401.00001v1`) or without the version before
importing them. A new version of a paper (`v2`) counts as a new record.

### 6. Assemble and run the pipeline

```python
import asyncio

from sci_etl_core import (
    AsyncCsvUpsertExporter,
    AsyncETLPipeline,
    AsyncSqliteStateManager,
    PipelineAborted,
)
from sci_etl_core.processors import DefaultKeyNormalizer


async def main() -> None:
    state = AsyncSqliteStateManager("state/pipeline.db")
    pipeline = AsyncETLPipeline(
        extractor=extractor,
        relevance_filter=relevance,
        entity_extractor=entities,
        exporter=AsyncCsvUpsertExporter(
            key_column="name",
            value_columns=["magnitude", "redshift"],
            normalizer=DefaultKeyNormalizer(),
        ),
        state_manager=state,
        destination="catalogue.csv",
        max_concurrency=config.pipeline.max_workers,
        logger=print,
        closeables=[client, llm, state],
    )
    async with pipeline:
        try:
            processed = await pipeline.run(
                query=config.pipeline.search_query,
                total_limit=config.pipeline.max_records,
            )
        except PipelineAborted as exc:
            print(f"Aborted after {exc.partial_count} records: {exc}")
            return
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

If the project is a blocking script, pass the same arguments to `ETLPipeline`
and call `pipeline.run(...)` inside a `with` block instead.

### 7. Point post-processing at the shared processors

```python
import pandas as pd

from sci_etl_core.processors import (
    DeduplicationStep,
    DefaultKeyNormalizer,
    NormalizationStep,
    ProcessorChain,
)

frame = pd.read_csv("catalogue.csv", dtype={"name": str})
chain = ProcessorChain(
    [
        NormalizationStep("name", DefaultKeyNormalizer()),
        DeduplicationStep("_norm_key"),
    ]
)
clean = chain.process(frame)
```

Rows whose name normalizes to an empty key are kept as separate rows rather
than merged. For fuzzy duplicate matching (for example by sky position), pass
your own `NeighborMatcher` to `DeduplicationStep(matcher=..., match_threshold=...)`.

### 8. Opt in to the extras you need

- [Semantic memory](README.md#semantic-memory-optional) to build a searchable
  vector store of full texts.
- [Graceful shutdown](README.md#graceful-shutdown) for long-running jobs that
  receive SIGINT/SIGTERM.
- [Rate limiting](README.md#rate-limiting) beyond `max_concurrency`.

### 9. Delete the old duplicated code

Once the injected components produce the same output, remove the project's
bespoke HTTP session, retry logic, semaphore juggling, state files handling,
and sync/async copies.

## Verifying the Migration

- Run against a small `total_limit` and diff the output CSV against a
  pre-migration run. Remember that `total_limit` counts relevant records only.
- Keep your prompts and normalizer identical at first; change behavior only
  after the outputs match.
- Search the log for `Record processing failed`. Those records weren't marked
  processed, and the saved offset stays at their page, so the next run retries
  them.
- If `run()` raises `PipelineAborted` because no record on a page could be
  processed, the cause is usually configuration, such as a rejected API key or
  an output CSV that can't be read; the exception's `__cause__` has the detail.
- If you wrote your own components, check them against the contracts in
  [Adding a New Component](CONTRIBUTING.md#adding-a-new-component).

Questions or a rough edge in your migration? Open an
[issue](.github/ISSUE_TEMPLATE/bug_report.md) — we're happy to help.
