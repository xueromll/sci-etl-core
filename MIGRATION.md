# Migration Guide

This guide has two parts:

- **[Part 1 — Upgrading from the generated sync facade](#part-1--upgrading-from-the-generated-sync-facade).**
  Read this if your code uses `ArxivExtractor`, `FileStateManager`, or other
  classes without the `Async` prefix, or if it runs `tools/generate_sync.py`.
- **[Part 2 — Moving a project onto sci-etl-core](#part-2--moving-a-project-onto-sci-etl-core).**
  Read this if you are replacing an in-repo pipeline. It uses `udg-catalogue`,
  the astronomy pipeline the library was extracted from, as the worked example,
  but every step is domain-agnostic.

---

## Part 1 — Upgrading from the generated sync facade

Earlier builds generated a blocking twin of every async class. The core
refactor (`3f45513`, `refactor(core)!`) removed them. Now the async classes are
the only implementations, and `ETLPipeline` is the single blocking entrypoint.
Later changes made failures raise instead of ending runs quietly, and added
SQLite state and embeddings.

### Removed and renamed APIs

| Removed | Use instead |
|---------|-------------|
| `ArxivExtractor` | `AsyncArxivExtractor` |
| `OpenAICompatibleClient` | `AsyncOpenAICompatibleClient` |
| `LLMRelevanceFilter` | `AsyncLLMRelevanceFilter` |
| `LLMEntityExtractor` | `AsyncLLMEntityExtractor` |
| `CsvUpsertExporter` | `AsyncCsvUpsertExporter` |
| `SqlTableExporter` | `AsyncSqlTableExporter` |
| `Plotly3DExporter` | `AsyncPlotly3DExporter` |
| `FileStateManager` | `AsyncFileStateManager`, or the new `AsyncSqliteStateManager` |
| `sci_etl_core.logging.configure_logging` | `sci_etl_core.log_utils.configure_logging` (also `from sci_etl_core import configure_logging`) |
| `sci_etl_core.__version__` | `importlib.metadata.version("sci-etl-core")` |
| `AsyncArxivExtractor(rate_limiter=...)` | wrap the extractor — see [Rate Limiting](README.md#rate-limiting) |
| `tools/generate_sync.py` | nothing; the library contains no generated code anymore |

Your own subclasses of the synchronous interfaces — `Extractor`,
`RelevanceFilter`, `EntityExtractor`, `LLMClient`, `Exporter`, and
`StateManager` — keep working: wrap each in its `Sync*Adapter` to pass it to
a pipeline (see [Synchronous Components](README.md#synchronous-components)).

### Calling components from blocking code

Before, each component had a blocking method:

```python
# old
extractor = ArxivExtractor(client=build_async_client(), pdf_parser=..., latex_parser=...)
listing = extractor.search("all:galaxy", max_results=25, start_index=0)
records, total = extractor.parse_listing(listing, seen_ids=set())
text = extractor.fetch_full_text(records[0])
```

Now, run a whole pipeline with `ETLPipeline` (see
[Blocking usage](README.md#blocking-usage)). For one-off calls, wrap the async
calls in a coroutine and run it:

```python
import asyncio

from sci_etl_core import AsyncArxivExtractor
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser


async def first_full_text() -> str:
    async with build_async_client() as client:
        extractor = AsyncArxivExtractor(
            client=client,
            pdf_parser=PdfPlumberParser(),
            latex_parser=LatexTarballParser(),
        )
        listing = await extractor.search("all:galaxy", max_results=25, start_index=0)
        records, _ = extractor.parse_listing(listing, seen_ids=set())  # still synchronous
        return await extractor.fetch_full_text(records[0])


text = asyncio.run(first_full_text())
```

`ETLPipeline` itself also changed:

- **Collaborators:** it takes async collaborators only.
- **New `run_timeout=` argument:** unlimited by default; raises `TimeoutError`
  when it expires.
- **Context manager:** `with` blocks close `closeables` on exit.
- **No attribute forwarding:** it no longer passes attribute access through to
  the underlying `AsyncETLPipeline`.

### Behavior changes to review

1. **Failures raise instead of ending the run quietly.**
   - **Before:** after exhausting retries, `AsyncArxivExtractor.search`
     returned `None`. The pipeline treated that as the end of the data and
     returned the partial count as if the run had finished.
   - **Now:** `search` raises `UpstreamError`, and an unparseable listing
     raises `MalformedResponseError`. `run()` wraps both in `PipelineAborted`,
     which carries `partial_count`.
   - **What to change:** catch `PipelineAborted` wherever you relied on the
     return value. Custom extractors should follow the same contract — raise
     on transport failures instead of returning `None` or an empty listing.
2. **Full-text fetching is stricter.**
   - **Before:** the LaTeX and PDF downloads were each tried once, and any
     failure fell back to the abstract.
   - **Now:** both downloads are retried with backoff. Only a definitive "not
     available" answer (such as 404) falls back to the abstract.
   - **Effect:** timeouts and repeated 429/5xx responses raise `UpstreamError`.
     The record is logged, left unmarked, and retried on the next run, instead
     of being processed permanently from its abstract.
3. **`AsyncFileStateManager.mark_processed` validates ids.** It strips
   surrounding whitespace and raises `ValueError` for ids containing line
   breaks.
4. **`AsyncCsvUpsertExporter` reads existing keys back as text.** Keys like
   `007` or `NaN` survive a reload. Duplicate keys within a single batch are
   merged into one row. If an existing CSV already has duplicate rows from an
   older build, deduplicate it once with `NormalizationStep` +
   `DeduplicationStep`; new exports won't add more.
5. **Writes are crash-safe.** CSV and metadata files are replaced atomically,
   and file state holds OS-level locks. No API change.
6. **New optional hooks.**
   - `AsyncStateManager.flush()` defaults to a no-op, so existing custom state
     managers keep working.
   - `AsyncETLPipeline(memory_ingestor=...)` adds [semantic memory](README.md#semantic-memory-optional).
7. **Paging continues past already-processed pages.** A listing page whose
   records had all been processed used to end the run silently; now paging
   moves on to the next page. `run(start_index=...)` overrides the saved
   offset — pass `0` to rescan a newest-first listing for new submissions.
8. **Entity-extraction failures are retried.** `AsyncLLMEntityExtractor.extract`
   used to return `[]` when the LLM call failed, so the record was marked
   processed with nothing exported. It now raises `LLMError`; the pipeline logs
   it and retries the record on the next run. Catch `LLMError` if you call
   `extract()` directly.
9. **Formula-like CSV keys are escaped.** `AsyncCsvUpsertExporter` now writes
   keys starting with `=`, `+`, `-`, `@`, a tab, or a carriage return (and keys
   starting with an apostrophe) with a leading apostrophe, and strips it on
   reload. Existing files are read as before, except that a key which already
   starts with an apostrophe loses it. Scripts that read the CSV directly will
   see the prefix; pass `escape_formulas=False` to keep the old output.
10. **Close the LLM client.** `AsyncOpenAICompatibleClient` now has `aclose()`;
    add it to `closeables` so its connections are released.
11. **The environment overrides a YAML API key.** `load_config` and
    `load_config_async` used to prefer `llm.api_key` from the YAML file over
    `LLM_API_KEY`. The environment variable now wins; the YAML value is used
    only when the variable is unset or empty.
12. **Optional dependencies load on first use.** `import sci_etl_core` no
    longer needs every extra. Install the extras for the components you use;
    importing a component whose extra is missing raises `ModuleNotFoundError`.

### Upgrade checklist

- [ ] Replace imports using the table above.
- [ ] Replace blocking component calls with `ETLPipeline`, or with async calls
      inside `asyncio.run`.
- [ ] Remove `rate_limiter=` arguments; wrap components if you need limits.
- [ ] Wrap your own synchronous component subclasses in `Sync*Adapter`s.
- [ ] Catch `PipelineAborted` around `run()`.
- [ ] Delete regenerated sync modules and any `tools/generate_sync.py` step in
      scripts or CI.
- [ ] Run once with a small `total_limit` against a copy of your state files
      and compare the output with a run from before the upgrade. The
      processed-ids and metadata file formats are unchanged, so existing state
      carries over.

---

## Part 2 — Moving a project onto sci-etl-core

### Why migrate

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

### What changes

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
requires it) and describes these response shapes:

- relevance: `{"relevant": bool}`
- extraction: `{"items": [...]}`, where each item includes the field you'll use
  as the CSV key

Both filters let records through when the LLM fails; pass
`default_on_error=False` to change that.

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

For fuzzy duplicate matching (for example by sky position), pass your own
`NeighborMatcher` to `DeduplicationStep(matcher=..., match_threshold=...)`.

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
- Search the log for `Record processing failed`; those records weren't marked
  processed and will be retried on the next run.
- Run `pytest`; the offline suite catches interface mismatches early.

Questions or a rough edge in your migration? Open an
[issue](.github/ISSUE_TEMPLATE/bug_report.md) — we're happy to help.
