# sci-etl-core

A reusable, **domain-agnostic** Python library for scientific text mining and
ETL. `sci-etl-core` gives you composable building blocks — extractors, parsers,
LLM clients, embedding memory, processors, exporters, and state managers —
behind abstract base classes, so you can assemble a pipeline for *any* corpus
without inheriting constants tied to a specific field of science.

The library is **async-first**. Every component is an `async` implementation,
orchestrated by `AsyncETLPipeline`. For scripts that don't want to manage an
event loop, `ETLPipeline` is a single blocking entrypoint that runs the same
pipeline on a background loop.

---

## Features

- **Pluggable async interfaces** for every stage: `AsyncExtractor`, `Parser`,
  `AsyncLLMClient`, `AsyncRelevanceFilter`, `AsyncEntityExtractor`,
  `AsyncExporter`, `AsyncStateManager`, plus `AsyncEmbedder`, `TextChunker`,
  and `AsyncEmbeddingStore` for semantic memory. Existing blocking
  implementations plug in through `Sync*Adapter` wrappers.
- **Built-in orchestration** — `AsyncETLPipeline` processes records with
  bounded concurrency; `ETLPipeline` wraps it for blocking code.
- **Explicit failure signaling** — a transport fault or malformed listing
  aborts the run with `PipelineAborted` (carrying the partial count) instead of
  looking like the end of the data. A single failing record is logged and
  skipped.
- **Resumable, crash-safe state** — plain-file or SQLite backends record
  processed ids and the listing offset; CSV and metadata writes use atomic
  renames.
- **Semantic memory (optional)** — chunk and embed full texts into an
  in-memory or SQLite vector store, search for similar articles, or gate
  relevance by embedding similarity instead of an LLM call.
- **Dependency injection everywhere** — HTTP clients, parsers, models,
  prompts, and destinations are constructor arguments.
- **Concrete implementations included** — arXiv extractor; OpenAI-compatible
  chat and embedding clients; local sentence-transformers embedder; PDF / LaTeX
  / HTML parsers; CSV upsert, SQL table, and 3D Plotly exporters; dataframe
  processors and record validators.
- **Typed configuration** from YAML + `.env` with Pydantic validation and
  `SecretStr` API keys.
- **Offline test suite** — pytest with mocks, Hypothesis property tests, and
  ABC conformance tests.
- **PEP 561 typed** (`py.typed`) for downstream type checking.

## Installation

Python 3.10 or newer is required.

```bash
pip install "sci-etl-core[async,llm,pdf]"   # everything the Quick Start uses
pip install "sci-etl-core[full]"            # every bundled component except local embeddings
# or, from a clone:
pip install -e ".[full]"
```

The base install covers configuration, both pipelines, the state backends, the
sync adapters, HTML and LaTeX parsing, text chunking, and the pandas processor
steps. Components load their optional dependencies only when you import them,
so add the extras for the components you use:

| Extra | Adds | Needed for |
|-------|------|------------|
| `async` | `httpx`, `aiofiles`, `aiolimiter` | `AsyncArxivExtractor`, `build_async_client`, `AsyncCsvUpsertExporter`, `load_config_async`, `AioLimiterRateLimiter` |
| `llm` | `openai`, `tiktoken` | `AsyncOpenAICompatibleClient`, token-based truncation |
| `pdf` | `pdfplumber` | `PdfPlumberParser` |
| `sql` | `sqlalchemy`, `aiosqlite` | `AsyncSqlTableExporter` |
| `viz` | `plotly`, `aiofiles` | `AsyncPlotly3DExporter` |
| `cluster` | `scikit-learn`, `numpy` | `ClusteringStep` |
| `embeddings` | `numpy`, `openai` | `AsyncOpenAIEmbedder`, the vector stores, `AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `numpy`, `sentence-transformers` | `AsyncSentenceTransformerEmbedder` |
| `dev` | pytest and plugins, `hypothesis` | running the test suite |

Importing a component whose extra is missing raises `ModuleNotFoundError`
naming the package to install.

## Quick Start

### Async pipeline

```python
import asyncio

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvUpsertExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.processors import DefaultKeyNormalizer

RELEVANCE_PROMPT = (
    "Decide whether the paper reports measurements of galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "Extract every measured object from the paper. Reply with JSON: "
    '{"items": [{"name": "...", "value_a": 0.0, "value_b": 0.0}]}.'
)


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(
        api_key="sk-...",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(
            client=client,
            pdf_parser=PdfPlumberParser(),
            latex_parser=LatexTarballParser(),
        ),
        relevance_filter=AsyncLLMRelevanceFilter(
            llm_client=llm, system_prompt=RELEVANCE_PROMPT
        ),
        entity_extractor=AsyncLLMEntityExtractor(
            llm_client=llm, system_prompt=EXTRACTION_PROMPT
        ),
        exporter=AsyncCsvUpsertExporter(
            key_column="name",
            value_columns=["value_a", "value_b"],
            normalizer=DefaultKeyNormalizer(),
        ),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        destination="results.csv",
        max_concurrency=4,
        logger=print,
        closeables=[client, llm],
    )

    async with pipeline:
        try:
            processed = await pipeline.run(query="all:galaxy", total_limit=50)
        except PipelineAborted as exc:
            print(f"Stopped early after {exc.partial_count} records: {exc}")
            return
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

What a run does:

1. Fetches a listing page (`page_size` records, default 100) starting at the
   offset saved by the state manager (or at `start_index=`, if given), and
   skips records already processed. A page that holds only processed records
   is passed over, not treated as the end of the data.
2. For each remaining record, with at most `max_concurrency` in flight:
   relevance filter → full-text fetch → optional memory ingest → entity
   extraction → export → mark processed. Irrelevant records are marked
   processed without fetching full text.
3. Saves the new listing offset, waits `sleep_between` seconds (default 0),
   and repeats until `total_limit` relevant records are processed or the
   listing is empty.

`total_limit` counts **relevant** records only, and defaults to `page_size`.
The legacy `max_records=` argument sets both values. `AsyncArxivExtractor` also
waits `sleep_before_search` seconds (default 3) before every listing request,
to respect arXiv's rate limits.

On exit, `async with pipeline` awaits `aclose()` on every entry in
`closeables` that has one — the HTTP client, the LLM client, and any SQLite
state manager or embedding store you use.

**Prompts must ask for JSON.** `AsyncOpenAICompatibleClient` requests JSON mode
(`response_format={"type": "json_object"}`), and OpenAI's API rejects JSON-mode
requests whose messages never mention "JSON". The response shapes the library
reads:

- `AsyncLLMRelevanceFilter` reads the boolean `relevant` key.
- `AsyncLLMEntityExtractor` reads the list under `result_key` (default
  `"items"`), or the only value if the response has exactly one key.
- `AsyncCsvUpsertExporter` takes each item's `key_column` value as the row key,
  so the extraction prompt must ask for that field.

### Blocking usage

`ETLPipeline` is the only synchronous class. It accepts the same arguments as
`AsyncETLPipeline` — including the same **async** collaborators — plus
`run_timeout`:

```python
from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvUpsertExporter,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    ETLPipeline,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.processors import DefaultKeyNormalizer

# RELEVANCE_PROMPT and EXTRACTION_PROMPT as in the async example.
client = build_async_client()
llm = AsyncOpenAICompatibleClient(
    api_key="sk-...",
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
)

with ETLPipeline(
    extractor=AsyncArxivExtractor(
        client=client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
    ),
    relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
    entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
    exporter=AsyncCsvUpsertExporter(
        key_column="name",
        value_columns=["value_a", "value_b"],
        normalizer=DefaultKeyNormalizer(),
    ),
    state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
    destination="results.csv",
    closeables=[client, llm],
    run_timeout=3600,
) as pipeline:
    try:
        processed = pipeline.run(query="all:galaxy", total_limit=50)
    except PipelineAborted as exc:
        processed = exc.partial_count

print(f"Processed {processed} relevant records")
```

- **There are no blocking versions of individual components.** To call an
  extractor, client, or exporter directly from synchronous code, wrap the calls
  in a coroutine and run it with `asyncio.run`. To plug your own blocking
  implementations into a pipeline, see
  [Synchronous Components](#synchronous-components).
- **`run_timeout`** is in seconds and unlimited by default. When it expires,
  the run is cancelled and `TimeoutError` is raised.
- **Event loop.** `ETLPipeline` runs the pipeline on a shared background
  event-loop thread. It works from plain scripts, and also when called from
  inside a running event loop (for example a notebook). It still blocks the
  calling thread until the run finishes, so in async code await
  `AsyncETLPipeline` instead. Once an `ETLPipeline` has used a collaborator,
  that collaborator belongs to the background loop — don't also use it from
  your own event loop.
- **`with ETLPipeline(...)`** closes `closeables` on exit, allowing up to 30
  seconds per resource.

### Configuration

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
print(config.llm.model, config.pipeline.max_records)
```

```yaml
# config.yaml
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
  sleep_between: 5.0
  max_workers: 6
```

| Section | Model | Fields (defaults) | Pass to |
|---------|-------|-------------------|---------|
| `llm` | `LLMConfig` | `api_key`, `base_url` (`https://api.openai.com/v1`), `model` (`gpt-4o-mini`), `timeout` (120) | `AsyncOpenAICompatibleClient` |
| `http` | `HttpConfig` | `user_agent` (`sci-etl-core/0.1`), `max_retries` (3), `backoff_factor` (2.0), `timeout` (25) | `build_async_client`, `AsyncArxivExtractor` |
| `full_text` | `RateLimitConfig` | `max_concurrency` (4), `max_rate` (unset), `time_period` (1.0) | `build_rate_limiter` |
| `pipeline` | `PipelineConfig` | `search_query` (`""`), `max_records` (100), `sleep_between` (5.0), `max_workers` (6) | `AsyncETLPipeline`, `run()` |

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
)
llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,  # a SecretStr is accepted as-is
    base_url=config.llm.base_url,
    model=config.llm.model,
    default_timeout=config.llm.timeout,
)
# Then: AsyncETLPipeline(..., max_concurrency=config.pipeline.max_workers)
# and:  run(query=config.pipeline.search_query,
#           total_limit=config.pipeline.max_records,
#           sleep_between=config.pipeline.sleep_between)
```

- **API key.** The key comes from the `LLM_API_KEY` environment variable
  (choose another with `api_key_env_var=`), which can be loaded from the
  `.env` file you pass. It is stored as a Pydantic `SecretStr`, so it doesn't
  show up in reprs or logs. Variables already set in the environment take
  precedence over `.env`; copy `.env.example` to get started.
- **The environment wins over YAML.** When the variable is set, it overrides
  any `llm.api_key` in the YAML file, which is used only as a fallback. Keep
  keys out of config files anyway.
- **Project-specific settings.** `BaseAppConfig` accepts extra top-level keys,
  or you can subclass it.
- **Async loading.** `load_config_async` takes the same arguments.
- **Errors.** A missing YAML file or a validation failure raises
  `ConfigurationError`.

## Post-Processing and Visualization

The pipeline's exporter receives each record's entities as a `list[dict]`, and
`AsyncCsvUpsertExporter` is the built-in exporter that accepts that shape. It
keeps one row per normalized key: later records only fill empty cells, value
columns are converted to floats (anything non-numeric becomes empty), and
optional `numeric_clip` bounds clamp them.

Keys come straight from LLM output, so a key a spreadsheet would run as a
formula (starting with `=`, `+`, `-`, `@`, a tab, or a carriage return) is
written with a leading apostrophe. The exporter strips it again when it
reloads the file; other tools reading the CSV see it. Pass
`escape_formulas=False` to write keys unchanged.

Cleanup, scoring, and plots are a separate step over a DataFrame:

```python
import asyncio

import pandas as pd

from sci_etl_core import AsyncPlotly3DExporter, ScatterPlotConfig
from sci_etl_core.processors import (
    CompletenessStep,
    DeduplicationStep,
    DefaultKeyNormalizer,
    NormalizationStep,
    ProcessorChain,
    QualityFlagStep,
)

frame = pd.read_csv("results.csv", dtype={"name": str})
clean = ProcessorChain(
    [
        NormalizationStep("name", DefaultKeyNormalizer()),  # adds _norm_key
        DeduplicationStep("_norm_key"),                     # one row per key
        CompletenessStep(["value_a", "value_b"]),           # adds completeness_pct
        QualityFlagStep(),                                  # adds quality_flag
    ]
).process(frame)

plot = AsyncPlotly3DExporter(
    ScatterPlotConfig(
        x_column="value_a",
        y_column="value_b",
        z_column="completeness_pct",
        color_column="quality_flag",
        hover_name_column="name",
        title="Corpus overview",
    )
)
asyncio.run(plot.export(clean, "overview.html"))
```

`clean` then looks like this:

| _norm_key | name     | value_a | value_b | completeness_pct | quality_flag   |
|-----------|----------|---------|---------|------------------|----------------|
| objecta   | Object A | 12.4    | 0.87    | 100.0            | Confirmed      |
| objectb   | Object B | 9.1     |         | 50.0             | Needs Review   |
| objectc   | Object C |         |         | 0.0              | Low Confidence |

The Plotly exporter drops rows that are missing any axis value. The other
building blocks:

- **`ClusteringStep(feature_extractor)`** runs DBSCAN over features returned by
  your own `FeatureExtractor`.
- **Record validators** check individual entity dicts: `NumericRangeValidator`,
  `KeywordExclusionValidator`, and `CompositeValidator`. The pipeline doesn't
  call them, so apply them in your own entity extractor or before export.
- **`AsyncSqlTableExporter(table_name)`** writes a DataFrame to a SQLAlchemy
  async URL, e.g.
  `await AsyncSqlTableExporter("entities").export(clean, "sqlite+aiosqlite:///results.db")`.
  Like the Plotly exporter, it takes a DataFrame, so use it after
  post-processing rather than as the pipeline's exporter.

## Semantic Memory (Optional)

Pass a `memory_ingestor` to chunk and embed each relevant record's full text
into a vector store. You can then search that store by meaning:

```python
from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)

embedder = AsyncOpenAIEmbedder(
    api_key="sk-...",
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
store = AsyncSqliteEmbeddingStore("memory.db")
ingestor = AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=store)

# Add to the pipeline from the Quick Start:
#   AsyncETLPipeline(..., memory_ingestor=ingestor, closeables=[client, embedder, store])


async def show_similar(text: str) -> None:
    finder = AsyncSimilarArticleFinder(embedder, store)
    for record_id, score, metadata in await finder.find_similar_articles(text, top_k=5):
        print(f"{score:.2f}  {record_id}  {metadata['title']}")
```

- **What gets stored.** Ingestion runs after the relevance gate, so only
  relevant records are embedded. `SlidingWindowChunker` defaults to 350-word
  windows with a 50-word overlap. Chunks are keyed by
  `(record_id, chunk_index)`, so re-ingesting a record replaces its chunks.
- **Failures.** An `EmbeddingError` or `EmbeddingStoreError` during ingestion
  is logged, and the record's entities are still exported.
- **Stores.** `InMemoryEmbeddingStore()` suits tests and short-lived runs.
  `AsyncSqliteEmbeddingStore` persists vectors with the standard-library
  `sqlite3` module and scans every stored vector on each query.
- **Local embeddings.** `AsyncSentenceTransformerEmbedder("all-MiniLM-L6-v2")`
  embeds without network calls. It needs the `embeddings-local` extra, loads
  the model when constructed, and accepts a preloaded `model=`.
- **Relevance without an LLM.** `AsyncEmbeddingRelevanceFilter` keeps a record
  when its title and abstract are close enough to any reference text:

  ```python
  from sci_etl_core import AsyncEmbeddingRelevanceFilter

  relevance_filter = AsyncEmbeddingRelevanceFilter(
      embedder=embedder,
      reference_texts=["ultra-diffuse galaxies", "low surface brightness galaxies"],
      threshold=0.35,  # minimum cosine similarity
  )
  ```

## State, Resuming, and Errors

Two state backends ship with the library:

- **`AsyncFileStateManager(processed_ids_file, metadata_file)`** stores one
  processed id per line plus a JSON metadata file. It holds OS-level file locks
  and writes metadata atomically.
- **`AsyncSqliteStateManager(database_path)`** uses a WAL-mode SQLite
  database. Add it to `closeables` so its connection is closed. Its `flush()`
  checkpoints the WAL.

Each run starts at the saved `last_start_index`, skips ids that were already
processed, and saves the new offset after every page. Records that fail
mid-run are never marked processed, so the next run retries them.

> **Newest-first listings.** The arXiv extractor lists the newest submissions
> first, so new papers push older ones to higher offsets. A run that resumes
> from the saved offset keeps working backwards through older papers and does
> not revisit the new ones. To pick those up, pass `start_index=0`: processed
> records are skipped by id, so a rescan costs listing requests (each preceded
> by the extractor's `sleep_before_search` delay) but reprocesses nothing.

| Situation | Behavior |
|-----------|----------|
| Listing request still fails after retries | `run()` raises `PipelineAborted` (cause: `UpstreamError`) |
| Listing payload can't be parsed | `run()` raises `PipelineAborted` (cause: `MalformedResponseError`) |
| Listing is valid but has no entries | `run()` returns the count normally |
| Listing page holds only already-processed records | paging continues with the next page |
| One record raises, e.g. a transient full-text failure | logged through `logger`; record left unmarked for the next run; other records continue |
| arXiv reports the LaTeX and PDF as unavailable (e.g. 404) | full text falls back to the abstract |
| LLM call fails inside `AsyncLLMRelevanceFilter` | returns `default_on_error` (**`True`**) |
| Record has an empty abstract | relevance filters return `default_on_empty_abstract` (**`True`**) |
| LLM call fails inside `AsyncLLMEntityExtractor` | `LLMError` propagates: logged, record left unmarked and retried on the next run |

All library exceptions derive from `SciEtlError`: `ExtractionError`
(`UpstreamError`, `MalformedResponseError`), `ParsingError`, `LLMError`,
`EmbeddingError`, `EmbeddingStoreError`, `ConfigurationError`, and
`PipelineAborted`. All of them can be imported from `sci_etl_core`.

## Graceful Shutdown

`ShutdownSignal` turns SIGINT/SIGTERM into a flag you can await. The pipeline
doesn't use it on its own, so run the pipeline as a task alongside it:

```python
import asyncio

from sci_etl_core.signals import ShutdownSignal


async def run_until_signalled(pipeline, state_manager, **run_kwargs):
    shutdown = ShutdownSignal(logger=print)
    with shutdown.guard():
        run = asyncio.create_task(pipeline.run(**run_kwargs))
        stop = asyncio.create_task(shutdown.wait())
        done, _ = await asyncio.wait({run, stop}, return_when=asyncio.FIRST_COMPLETED)
        for task in (run, stop):
            if task not in done:
                task.cancel()
        await asyncio.gather(run, stop, return_exceptions=True)
    await state_manager.flush()
    return None if run.cancelled() else run.result()
```

- **First signal:** sets the flag. Cancelled in-flight records stay unmarked
  and are retried on the next run.
- **Second signal:** restores the previous handler and terminates immediately.
- **Where it works:** call `guard()` from async code on the main thread; on any
  other thread it logs a message and installs nothing. That means it can't be
  used through `ETLPipeline`, whose loop runs on a background thread.

## Rate Limiting

`AsyncETLPipeline(max_concurrency=...)` bounds how many records are processed
at once. For finer control, `sci_etl_core.rate_limiter` provides standalone
async context managers:

- `SemaphoreRateLimiter` — concurrency cap
- `AioLimiterRateLimiter` — token bucket; needs the `async` extra
- `NullRateLimiter` — no limit

`build_rate_limiter(max_concurrency, max_rate, time_period)` returns a token
bucket when `max_rate` is set and a semaphore otherwise. Its parameters match
the `full_text` config section. Components don't take a limiter argument, so
apply one by wrapping a component:

```python
from sci_etl_core.extractors import AsyncExtractor
from sci_etl_core.rate_limiter import AsyncRateLimiter, build_rate_limiter


class RateLimitedExtractor(AsyncExtractor):
    """Route an extractor's network calls through one shared limiter."""

    def __init__(self, inner: AsyncExtractor, limiter: AsyncRateLimiter) -> None:
        self._inner = inner
        self._limiter = limiter

    async def search(self, query, max_results, start_index):
        async with self._limiter:
            return await self._inner.search(query, max_results, start_index)

    def parse_listing(self, raw_listing, seen_ids):
        return self._inner.parse_listing(raw_listing, seen_ids)

    async def fetch_full_text(self, record):
        async with self._limiter:
            return await self._inner.fetch_full_text(record)


# extractor = RateLimitedExtractor(AsyncArxivExtractor(...), build_rate_limiter(**config.full_text.model_dump()))
```

## Synchronous Components

To reuse blocking implementations, subclass the synchronous interfaces and
wrap each object in its adapter. The result can be passed to either pipeline:

| Sync interface | Adapter | Where the calls run |
|----------------|---------|---------------------|
| `Extractor` | `SyncExtractorAdapter` | `fetch_full_text` in a worker thread; `search` and `parse_listing` on the event loop, between pages |
| `RelevanceFilter` | `SyncRelevanceFilterAdapter` | worker thread |
| `EntityExtractor` | `SyncEntityExtractorAdapter` | worker thread |
| `LLMClient` | `SyncLLMClientAdapter` | worker thread |
| `Exporter` | `SyncExporterAdapter` | on the event loop, so exports never interleave |
| `StateManager` | `SyncStateManagerAdapter` | on the event loop, so updates are never lost |

```python
import json

from sci_etl_core import Exporter, SyncExporterAdapter


class JsonLinesExporter(Exporter):
    def export(self, data, destination):
        with open(destination, "a", encoding="utf-8") as handle:
            for row in data:
                handle.write(json.dumps(row) + "\n")


exporter = SyncExporterAdapter(JsonLinesExporter())
# AsyncETLPipeline(..., exporter=exporter)
```

Calls that run on the event loop block it while they run: a slow exporter or
state manager stalls every record in flight. Keep those calls fast, or
implement the async interface instead.

## Logging

`configure_logging(name, log_file, level=logging.INFO)` returns a
`logging.Logger` that writes to a file and to stdout. Components take a plain
`logger` callable, so pass a bound method:

```python
from sci_etl_core import configure_logging

log = configure_logging("my_pipeline", "pipeline.log")
# AsyncETLPipeline(..., logger=log.warning)
# AsyncArxivExtractor(..., logger=log.info)
```

## Architecture

```
ETLPipeline (blocking) --runs on a background event loop--> AsyncETLPipeline.run(query)
                                                                  |
  +---------------------------------------------------------------+
  v
AsyncExtractor.search --> parse_listing --> records not yet in AsyncStateManager
                                                  |  (max_concurrency at a time)
                                                  v
                          AsyncRelevanceFilter.is_relevant --no--> mark processed
                                                  | yes
                                                  v
                          AsyncExtractor.fetch_full_text (LaTeX -> PDF -> abstract)
                                                  |
                                                  +--> AsyncChunkIngestor (optional)
                                                  |      TextChunker -> AsyncEmbedder
                                                  |      -> AsyncEmbeddingStore
                                                  v
                          AsyncEntityExtractor.extract
                                                  |
                                                  v
                          AsyncExporter.export(entities, destination) --> mark processed

After each page: AsyncStateManager.save_metadata(last_start_index)
```

| Layer | Interface | Implementations | Import from |
|-------|-----------|-----------------|-------------|
| Extract | `AsyncExtractor` | `AsyncArxivExtractor` | `sci_etl_core.extractors` |
| Parse | `Parser`, `TableParser` | `PdfPlumberParser`, `LatexTarballParser`, `HtmlTextParser` | `sci_etl_core.parsers` |
| LLM | `AsyncLLMClient` | `AsyncOpenAICompatibleClient` | `sci_etl_core.llm` |
| Relevance | `AsyncRelevanceFilter` | `AsyncLLMRelevanceFilter`, `AsyncEmbeddingRelevanceFilter` | `sci_etl_core.llm` |
| Entities | `AsyncEntityExtractor` | `AsyncLLMEntityExtractor` | `sci_etl_core.llm` |
| Export | `AsyncExporter` | `AsyncCsvUpsertExporter` (list of dicts); `AsyncSqlTableExporter`, `AsyncPlotly3DExporter` (DataFrame) | `sci_etl_core.exporters` |
| State | `AsyncStateManager` | `AsyncFileStateManager`, `AsyncSqliteStateManager` | `sci_etl_core.state` |
| Embeddings | `AsyncEmbedder` | `AsyncOpenAIEmbedder`, `AsyncSentenceTransformerEmbedder` | `sci_etl_core.embeddings` |
| Chunking | `TextChunker` | `SlidingWindowChunker` | `sci_etl_core.embeddings` |
| Vector memory | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`, `AsyncSqliteEmbeddingStore` | `sci_etl_core.embeddings` |
| Post-processing | `Processor`, `RecordValidator` | `ProcessorChain`, `NormalizationStep`, `DeduplicationStep`, `ClusteringStep`, `CompletenessStep`, `QualityFlagStep`; `NumericRangeValidator`, `KeywordExclusionValidator`, `CompositeValidator` | `sci_etl_core.processors` |
| Sync adapters | `Extractor`, `RelevanceFilter`, `EntityExtractor`, `LLMClient`, `Exporter`, `StateManager` | `Sync*Adapter` for each | `sci_etl_core` |
| Orchestration | — | `AsyncETLPipeline`, `ETLPipeline` | `sci_etl_core` |

The pipelines, stage interfaces, adapters, and most implementations are also
re-exported from `sci_etl_core` itself; parser implementations, processor
steps, and validators come from their subpackages. Supporting modules:
`sci_etl_core.config`, `sci_etl_core.http_async` (`build_async_client`),
`sci_etl_core.rate_limiter`, `sci_etl_core.signals`, `sci_etl_core.log_utils`,
and `sci_etl_core.exceptions`. Every package loads its public names on first
access, so importing one component never requires another component's
optional dependencies.

## Testing

```bash
pip install -e ".[full,dev]"
pytest                                                # full suite
pytest --cov=sci_etl_core --cov-report=term-missing   # with coverage
```

The suite runs offline: HTTP, LLM, and embedding calls are mocked, and a stub
replaces SQLAlchemy when it isn't installed. Hypothesis property tests and ABC
conformance tests guard the public interfaces, and `pytest --cov` fails if line
coverage drops below 100%.

## Contributing

Contributions are welcome — new extractors, parsers, exporters, and embedding
backends especially. See [CONTRIBUTING.md](CONTRIBUTING.md) to get set up, and
browse [good first issues](.github/ISSUE_TEMPLATE/good_first_issue.md) if
you're new. Upgrading from an older build? See [MIGRATION.md](MIGRATION.md).
All participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

Released under the MIT License. See [LICENSE](LICENSE) for details.
