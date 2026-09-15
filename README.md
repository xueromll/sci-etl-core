# sci-etl-core

[![CI](https://github.com/xueromll/sci-etl-core/actions/workflows/ci.yml/badge.svg)](https://github.com/xueromll/sci-etl-core/actions/workflows/ci.yml)

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

## Table of Contents

- [Features](#features)
- [Supported Sources](#supported-sources)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Post-Processing and Visualization](#post-processing-and-visualization)
- [Semantic Memory (Optional)](#semantic-memory-optional)
- [Local Search and Discovery](#local-search-and-discovery)
- [State, Resuming, and Errors](#state-resuming-and-errors)
- [Graceful Shutdown](#graceful-shutdown)
- [Retries](#retries)
- [Rate Limiting](#rate-limiting)
- [Synchronous Components](#synchronous-components)
- [Logging](#logging)
- [Token Usage](#token-usage)
- [Architecture](#architecture)
- [Testing](#testing)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)



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
  looking like the end of the data. A single failing record is logged and left
  for the next run, and records that keep failing while nothing is processed
  stop the run instead of burning through the rest of the listing.
- **Resumable, crash-safe state** — plain-file or SQLite backends record
  processed ids and the listing offset; CSV and metadata writes use atomic
  renames.
- **Polite retries** — the arXiv extractor and the OpenAI-compatible chat and
  embedding clients wait as long as a throttled response's `Retry-After`
  header asks, up to a configurable cap.
- **Token usage** — the OpenAI-compatible clients count the tokens each
  response reports, so a run's API cost can be shown.
- **Semantic memory (optional)** — chunk and embed full texts into an
  in-memory or SQLite vector store, search for similar articles, or gate
  relevance by embedding similarity instead of an LLM call.
- **Local search and discovery** — Boolean queries over a SQLite FTS5 text
  index that needs only the standard library, hybrid search that fuses BM25
  with embedding similarity, metadata facets, and graphs of related papers.
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

## Supported Sources

`AsyncArxivExtractor` is the only extractor that ships with the library. Every
source has its own protocol, pagination model, ID scheme, and full-text
formats, so each one gets its own `AsyncExtractor` rather than a single
extractor with switches for every source. The pipeline works with any class
that implements this contract:

```python
from sci_etl_core import AsyncExtractor
from sci_etl_core.models import RawRecord


class MySourceExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None: ...

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...
```

- **`search`** returns one raw listing page. If the source can't be reached,
  it raises `UpstreamError` instead of returning an empty value; if the source
  rejects the request outright, it raises `ExtractionError`. Either one aborts
  the run.
- **`parse_listing`** returns the records whose ids aren't in `seen_ids`, plus
  the number of entries on the page, counting the skipped ones. A count of `0`
  ends the run. If the payload can't be read, it raises
  `MalformedResponseError`.
- **`fetch_full_text`** returns the best text available for a record.

| Source | Status | How to use it |
|--------|--------|---------------|
| arXiv | Bundled | `AsyncArxivExtractor` |
| bioRxiv | Not bundled | Adapt `AsyncArxivExtractor` |
| ChemRxiv | Not bundled | Adapt `AsyncArxivExtractor` |
| PubMed | Not bundled | Implement your own `AsyncExtractor` |
| Crossref | Not bundled | Implement your own `AsyncExtractor` |



## Installation

Python 3.10 or newer is required.

```bash
pip install "sci-etl-core[async,llm,pdf]"   # everything the Quick Start uses
pip install "sci-etl-core[full]"            # every bundled component except local embeddings
# or, from a clone:
pip install -e ".[full]"
```

The base install covers configuration, both pipelines, the state backends, the
sync adapters, HTML and LaTeX parsing, text chunking, Boolean text search,
rank fusion, discovery graphs, and the pandas processor steps. Components load their optional dependencies only when you import them,
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
| `search` | nothing | nothing extra: `sci_etl_core.search` needs only the standard library, so this extra just records why the package is installed |
| `dev` | pytest and plugins, `hypothesis` | running the test suite |
| `lint` | `ruff`, `mypy`, type stubs | linting and type-checking the source |

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
   processed without fetching full text. Records whose `record_id` is missing
   or blank can't be tracked, so they are skipped and logged.
3. Saves the listing offset and repeats until `total_limit` relevant records
   are processed or the listing is empty, waiting `sleep_between` seconds
   (default 0) before each further page. The offset only moves past pages
   whose records were all settled; see
   [State, Resuming, and Errors](#state-resuming-and-errors).

`total_limit` counts **relevant** records only, is never exceeded, and defaults
to `page_size`. `max_concurrency` and `page_size` must be at least 1 and
`total_limit` must not be negative; other values raise `ValueError` before any
request is made. The legacy `max_records=` argument sets both values. `AsyncArxivExtractor` also
waits `sleep_before_search` seconds (default 3) before every listing request,
to respect arXiv's rate limits.

On exit, `async with pipeline` awaits `aclose()` on every entry in
`closeables` that has one — the HTTP client, the LLM client, and any
`AsyncSqliteStateManager`, `AsyncSqliteEmbeddingStore`, or
`AsyncSqliteFts5Store` you use.

**Prompts must ask for JSON.** `AsyncOpenAICompatibleClient` requests JSON mode
(`response_format={"type": "json_object"}`), and OpenAI's API rejects JSON-mode
requests whose messages never mention "JSON". The response shapes the library
reads:

- `AsyncLLMRelevanceFilter` reads the `relevant` key. It accepts a boolean,
  `0`/`1`, or the strings `"true"`, `"false"`, `"yes"`, `"no"`, `"1"`, and
  `"0"` in any case. Anything else, including a missing key, is treated as an
  error and returns `default_on_error`.
- `AsyncLLMEntityExtractor` reads the list under `result_key` (default
  `"items"`), or the only value if the response has exactly one key. The list
  must hold objects; `null` means no entities and a lone object counts as one.
  Any other shape raises `LLMError`, so the record is retried.
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
    api_key=config.llm.api_key,  # a SecretStr is accepted as-is
    base_url=config.llm.base_url,
    model=config.llm.model,
    default_timeout=config.llm.timeout,
)
# Then: AsyncETLPipeline(..., max_concurrency=config.pipeline.max_workers)
# and:  run(query=config.pipeline.search_query,
#           page_size=config.pipeline.page_size,
#           total_limit=config.pipeline.max_records,
#           sleep_between=config.pipeline.sleep_between)
```

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

## Post-Processing and Visualization

The pipeline's exporter receives each record's entities as a `list[dict]`, and
`AsyncCsvUpsertExporter` is the built-in exporter that accepts that shape. It
keeps one row per normalized key: later records only fill empty cells, value
columns are converted to floats (anything non-numeric becomes empty), and
optional `numeric_clip` bounds clamp them.

The exporter reads the existing file (which must be UTF-8) before its first
write. If that read fails, for example because of a different encoding or a
malformed row, the export raises and the file is left untouched instead of
being overwritten. On Windows, a write is retried for about a second and a
half while another program holds the file open.

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
  windows with a 50-word overlap. Re-ingesting a record replaces all of its
  chunks, so text that now yields fewer passages leaves nothing stale behind.
- **Failures.** An `EmbeddingError` or `EmbeddingStoreError` during ingestion
  is logged, and the record's entities are still exported. That includes a
  memory file that isn't a SQLite database, and an embedder that returns a
  different number of vectors than passages.
- **Stores.** `InMemoryEmbeddingStore()` suits tests and short-lived runs.
  `AsyncSqliteEmbeddingStore` persists vectors with the standard-library
  `sqlite3` module and scans every stored vector on each query. It serializes
  access to its connection, so concurrent records can share one store, and
  each write is a single transaction. A stored vector holding NaN or infinity
  never appears in results.
- **Custom stores.** Subclasses of `AsyncEmbeddingStore` implement `add`,
  `delete_record`, `query`, and `count`. `replace_record` defaults to delete
  then add; override it if your backend can do both atomically.
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

To index the same records for Boolean search as well, see
[Local Search and Discovery](#local-search-and-discovery). Its SQLite text
index, `AsyncSqliteFts5Store`, is one more store to list in `closeables`
beside the embedding store, and its `search` extra installs nothing.

## Local Search and Discovery

A text index next to the vector memory adds Boolean search, hybrid search that
fuses keyword and meaning-based rankings, metadata facets, and graphs of
related papers. All of it lives in `sci_etl_core.search` and needs only the
standard library's `sqlite3`, so it works on a bare `pip install sci-etl-core`.
The `search` extra installs nothing; it only lets a requirements file say why
the package is there. Only the semantic side needs the `embeddings` extra.

This example extends the one in [Semantic Memory](#semantic-memory-optional),
so that each relevant record is indexed for both kinds of search:

```python
from sci_etl_core import AsyncCompositeIngestor
from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)
from sci_etl_core.search import AsyncHybridSearcher, AsyncSearchIndexer, AsyncSqliteFts5Store

embedder = AsyncOpenAIEmbedder(
    api_key="sk-...",
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
vector_store = AsyncSqliteEmbeddingStore("memory.db")
text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))

ingestor = AsyncCompositeIngestor(
    AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=vector_store),
    AsyncSearchIndexer(store=text_store),
    logger=print,
)

# Add to the pipeline from the Quick Start:
#   AsyncETLPipeline(
#       ...,
#       logger=print,
#       memory_ingestor=ingestor,
#       closeables=[client, llm, embedder, vector_store, text_store],
#   )


async def show_matches(query: str) -> None:
    searcher = AsyncHybridSearcher(text_store, AsyncSimilarArticleFinder(embedder, vector_store))
    outcome = await searcher.search(query, top_k=10)
    if outcome.degraded:
        print(f"Degraded: {', '.join(outcome.degraded)}")
    for hit in outcome.hits:
        print(f"{hit.score:.4f}  {hit.record_id}  {hit.title}")
```

- **Closing the stores.** `text_store` belongs in `closeables` for the same
  reason `vector_store` does, because this is a one-shot script: the pipeline
  owns both stores, so `show_matches` must run inside `async with pipeline`. A
  long-lived application follows [Store ownership](#store-ownership) instead.
- **One log stream.** The same `logger` goes to the composite and the
  pipeline, so memory faults appear in one stream. A `SearchStoreError` while
  indexing is logged as `Memory ingest failed for <record_id> in
  AsyncSearchIndexer: ...`, and the record's chunks are still embedded and its
  entities still exported. An embedding fault likewise leaves the text index
  unaffected. A `SearchQueryError` is not a memory fault and fails the record.
- **Ingestor order.** `AsyncCompositeIngestor` returns its first ingestor's
  count, so pass the chunk ingestor first; an `AsyncSearchIndexer` in first
  place raises `ValueError`. Without embeddings, pass an `AsyncSearchIndexer`
  straight to `memory_ingestor=`.
- **What gets indexed.** One document per record, holding its title, abstract,
  full text, and `metadata`. Re-ingesting a record replaces its document, and
  a record whose title, abstract, and text are all blank is removed.

### Query syntax

| Construct | Example | Matches |
|-----------|---------|---------|
| Term | `galaxy` | the word, ignoring case and accents, so `Müller` matches `Muller` |
| Phrase | `"dwarf galaxy"` | the words next to each other, in order |
| Prefix | `photometr*` | any word starting with `photometr` |
| Field scope | `title:quasar`, `title,abstract:"dwarf galaxy"` | only in the named fields: `title`, `abstract`, `body` |
| And | `a AND b`, `a && b`, `a b` | both |
| Or | `a OR b`, `a \|\| b` | either |
| Not | `NOT a`, `-a` | documents without `a` |
| Grouping | `(a OR b) -c` | |

`NOT` binds tightest, then `AND`, then `OR`. Operators are upper case, so
`and` is an ordinary word. A word the tokenizer splits, such as `H-alpha`, is
searched as a phrase of its parts.

Parsing is pure and synchronous, so a query bar can run it on every keystroke.
A malformed query raises `SearchQueryError`, whose `position` and `token` point
at the fault, and `describe` returns the parsed words and phrases as
`QueryChip`s for display:

```python
from sci_etl_core import SearchQueryError
from sci_etl_core.search import describe, parse_query

try:
    chips = describe(parse_query("title:quasar (blazar OR -dwarf"))
except SearchQueryError as exc:
    print(f"{exc} (column {exc.position}: {exc.token!r})")
```

### Ranked search and plain filtering

The stores take parsed queries, and `AsyncHybridSearcher` takes text and parses
it once, before any I/O. A ranked search needs a term to rank by, so a query
whose every term is negated, such as `NOT simulation` or
`NOT simulation OR quasar`, raises `SearchQueryError` from `search`. Ask
`filter_ids` instead. It accepts any query and returns a `frozenset` of record
ids, which carries no order and so can't be mistaken for a ranking:

```python
from sci_etl_core.search import parse_query

hits = await text_store.search(parse_query("photometr* dwarf"), limit=20)
observational = await text_store.filter_ids(parse_query("NOT simulation"))
```

A `TextHit` has a `score` where higher is better. Its scale depends on the
corpus, so compare scores only within one result list. Its `snippet` is plain
text from one field, and `highlights` holds `[start, end)` character offsets
into it for the matched words, so the UI applies its own markup.

### Hybrid search

`AsyncHybridSearcher(text_store, finder).search(query, top_k, mode=..., filters=...)`
runs one or both retrieval legs:

| `mode` | Runs | Without a `finder` |
|--------|------|--------------------|
| `"lexical"` | BM25 over the text index | unaffected |
| `"semantic"` | the vector memory, scoring each article by its best chunk | raises `SearchQueryError` |
| `"hybrid"` (default) | both at once, then fuses the two rankings | runs the lexical leg only and reports `skipped=("semantic",)` |

- **What the embedder sees.** The semantic leg embeds the query's words, not
  its syntax. Operators, field scopes, negated terms, and prefix terms are
  dropped, so `quasar -dwarf` is embedded as `quasar`, and `quasar OR blazar`
  the same as `quasar blazar`. A hybrid query made only of prefix terms skips
  the semantic leg; in semantic mode it raises `SearchQueryError`.
- **Degraded and skipped legs.** `SearchOutcome.degraded` names legs that were
  attempted and failed. In hybrid mode, an `EmbeddingError` is logged through
  `logger`, and the lexical results are returned. `SearchOutcome.skipped`
  names legs that had nothing to run. Tell the user about both. A lexical
  failure is always raised, because it means the local index is broken.
- **Fusion.** Reciprocal rank fusion reads only the order of each list, so
  BM25's corpus-dependent scale never skews the blend. Pass
  `strategy=normalized_score_fusion` when score gaps should count, and
  `fusion=FusionParams(weights=(1.0, 2.0))` to weigh the lexical and semantic
  lists, in that order.
- **Hits.** A `FusedHit` carries `lexical_rank` and `semantic_rank` (`None`
  where that leg did not return it), `title`, `metadata`, and the lexical
  snippet and highlights. Show ranks, never the fused score as a percentage. A
  record found only by the semantic leg has no snippet; read its abstract with
  `text_store.get_documents`.
- **Candidate pool.** Each leg fetches `HybridParams.candidate_pool` records
  (default 100, and never fewer than `top_k`) before fusion, so a record
  ranked 40th lexically and 3rd semantically can still reach the top 20. The
  semantic leg asks the vector memory for `candidate_pool × chunk_pool_factor`
  chunks (default factor 5). Raise the factor when long articles fill the top
  chunks and the pool comes back short.

### Filters and facets

Metadata filters are `MetadataFilter` values passed beside the query, never
written into it. A store tags each document under the metadata keys named in
its `facet_keys`. `AsyncArxivExtractor` fills `categories`, `authors`,
`published`, and `year` in `RawRecord.metadata`, and `AsyncSearchIndexer`
copies that metadata into the index.

```python
from sci_etl_core.search import MetadataFilter, parse_query

filters = (
    MetadataFilter("categories", {"astro-ph.GA", "astro-ph.CO"}),
    MetadataFilter("year", {"2020", "2021"}, negated=True),
)
outcome = await searcher.search("dwarf galaxy", filters=filters)
facets = await text_store.facet_counts(["categories", "year"], query=parse_query("dwarf galaxy"), filters=filters)
```

- **Matching.** A filter keeps the records tagged with any of its values, and
  with `negated=True` drops them. Every filter must pass. Several values of one
  key go in one filter: two filters on the same key, or a key outside
  `facet_keys`, raise `ValueError` before any I/O.
- **Tags.** Strings, integers, and lists of them become tags; other values are
  not tagged. Matching is exact, so there are no range filters over dates or
  years.
- **Before the limit.** Filters are applied inside the index, before `limit`,
  and to both legs of a hybrid search, so a filtered-out record never takes a
  result slot.
- **Facet counts.** `facet_counts` maps each key to `(value, count)` pairs,
  sorted by count and then value, without zero counts. Each key's counts apply
  the query and every filter on *other* keys, so a count says how many results
  selecting that value would give, and the other values of a filtered key stay
  visible. `query=None` counts across the whole index.
- **Changing `facet_keys`.** The keys are fixed when a store is constructed
  and recorded in the file. To change them, construct the store with the new
  keys and `await text_store.rebuild_tags()`. Until then, a filter or facet on
  a key whose tags aren't built raises `SearchStoreError`.

### Text stores

- **`InMemoryTextSearchStore(facet_keys=...)`** suits tests and short-lived
  runs. It matches exactly the records the SQLite store matches and scores
  with the same BM25 formula.
- **`AsyncSqliteFts5Store(path, facet_keys=..., weights=...)`** persists the
  index. Each article's text is stored once, each write is one transaction,
  and every SQLite failure, including a file that isn't a database, raises
  `SearchStoreError`. `weights=BM25Weights(title=10.0, abstract=4.0, body=1.0)`
  sets how much a match in each field counts; those are the defaults.
- **FTS5 is required.** The store needs a Python whose SQLite was built with
  FTS5, and raises `SearchStoreError` when it is constructed otherwise.
  `fts5_available()` checks in advance; `InMemoryTextSearchStore` works
  everywhere.
- **Maintenance is explicit.** `optimize()` merges the index's segments.
  `integrity_check()` returns `False` when the index disagrees with the stored
  documents, for example after the file was edited by other tools, and
  `rebuild_index()` repairs it from the stored text without fetching anything.
  A file created by a newer version of the library raises `SearchStoreError`
  rather than being used.
- **Custom stores** subclass `AsyncTextSearchStore`; see
  [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-new-component).

### Discovery graphs

`build_discovery_graph` grows a graph of related papers around a seed record,
in the spirit of Connected Papers, from edge sources that relate records by
similarity:

```python
from sci_etl_core.search import (
    EmbeddingEdgeSource,
    GraphParams,
    MetadataEdgeSource,
    MetadataFilter,
    build_discovery_graph,
    filter_graph,
)


async def show_neighborhood(record_id: str) -> None:
    sources = [
        EmbeddingEdgeSource(embedder, vector_store, text_store),
        MetadataEdgeSource(text_store, keys=("categories",)),
    ]
    graph = await build_discovery_graph(record_id, sources, text_store, params=GraphParams(depth=2, fanout=8))
    recent = filter_graph(graph, filters=[MetadataFilter("year", {"2025", "2026"})])
    for node in recent.nodes:
        print(f"community {node.community}  links {node.degree}  {node.title}")
```

- **Edge sources.** `EmbeddingEdgeSource` relates records whose title and
  abstract are close in the vector memory, and `MetadataEdgeSource` records
  that share tags, weighted by the Jaccard index of their tag sets. Its keys
  must be among the text store's `facet_keys`, and it defaults to
  `("categories", "authors")`. Other notions of relatedness, such as
  citations, plug in as subclasses of `AsyncEdgeSource`.
- **Growth.** The graph grows `depth` levels. Each record adds up to `fanout`
  neighbors per source whose weight is at least `min_weight` (default 0.35),
  and `max_nodes` (default 200) is checked before each level. With
  `mutual_only` (the default), an edge is kept only when each record is among
  the other's nearest, which keeps a hub paper from linking to everything.
  Only records connected to the seed remain.
- **Communities.** `GraphNode.community` comes from label propagation, which
  is deterministic: the same graph always gives the same communities. When
  `max_iterations` (default 20) cuts it short,
  `DiscoveryGraph.communities_converged` is `False`, and a UI should say the
  communities are approximate.
- **Topology only.** Nodes and edges carry no coordinates or colors; the UI
  runs its own layout.
- **Filtering without I/O.** `filter_graph` is pure and synchronous, so a UI
  can re-run it on every facet toggle. The seed always stays, edges that lose
  an endpoint are dropped, and communities are kept so colors stay stable.
  Pass `matched_ids=await text_store.filter_ids(parse_query(...))` to keep only
  records matching a query; that call accepts pure negation, such as
  `NOT simulation`.
- **Cost.** `EmbeddingEdgeSource` issues up to one vector query per node, and
  `AsyncSqliteEmbeddingStore` scans every stored chunk on each query, so keep
  `max_nodes` small for a large memory.

### Building a user interface

`sci_etl_core.discovery` holds the read-model a presentation layer renders:
`DiscoveryResult` (the query text and chips, fused hits, graph, facets,
matched count, elapsed time, and degraded and skipped legs) and `Facet`. Both
are frozen dataclasses, and importing the module loads no store, no event-loop
machinery, and no optional dependency. Keep parsing on the keystroke and make
only retrieval asynchronous: debounce it, cancel a search when a newer one
starts, and drop any result that arrives after a newer search began.

### Store ownership

Three facts make it matter who closes a store:

- `aclose()` on a SQLite store isn't final: a later call reopens the
  connection.
- `async with pipeline` closes every entry in `closeables` each time the block
  exits.
- A store's lock belongs to the first event loop that contends for it. Using
  the same instance from a second loop fails, but only when both use it at
  once, so a quiet test passes and a busy UI breaks.

So give every store instance exactly **one owner**, the scope that outlives
all its users, and let only the owner call `aclose()`. Use each instance from
**one event loop**. Everything else borrows: `AsyncHybridSearcher`, the edge
sources, and `AsyncCompositeIngestor` never close a store.

| Deployment | Owner of the SQLite stores | Pipeline `closeables` |
|------------|----------------------------|-----------------------|
| Pipeline and UI in separate processes | each process, for the instances it opened on the shared files | lists the pipeline's own instances |
| One-shot script that ingests and queries inside `async with pipeline` | the pipeline | lists the stores; queries run inside the block |
| Long-lived application on one event loop that starts ingest runs | the application, which closes them on shutdown | must **not** list them, or the end of each run closes them and the next query reopens an unowned connection |
| Blocking `ETLPipeline` plus an application on its own loop | two sets of instances on the same files: one used by the pipeline's background loop, one by the application's loop | lists the pipeline's set |

SQLite's WAL mode lets one process read while another writes.

## State, Resuming, and Errors

Two state backends ship with the library:

- **`AsyncFileStateManager(processed_ids_file, metadata_file)`** stores one
  processed id per line plus a JSON metadata file. It holds OS-level file locks
  and writes metadata atomically.
- **`AsyncSqliteStateManager(database_path)`** uses a WAL-mode SQLite
  database. Add it to `closeables` so its connection is closed. Its `flush()`
  checkpoints the WAL.

Each run starts at the saved `last_start_index` and skips ids that were
already processed. The offset is saved after every page, but it only moves
past a page once every record on it is settled, meaning processed or marked
irrelevant. When a record fails, or is left over because `total_limit` was
reached, the offset stays at the start of that page for the rest of the run,
so the next run revisits it while skipping everything already processed.

Records are exported before they are marked processed, so a crash between the
two re-exports that record on the next run. `AsyncCsvUpsertExporter` absorbs
this; an appending exporter of your own should tolerate duplicates.

`AsyncFileStateManager` raises `OSError` when a state file exists but can't be
read, rather than treating it as empty. It rejects record ids that contain a
line boundary or have leading or trailing whitespace, since neither would read
back unchanged. Metadata content that isn't valid falls back to offset 0, which
only costs a rescan. Both backends record `last_run_at` as an ISO 8601
timestamp in UTC.

> **Newest-first listings.** The arXiv extractor lists the newest submissions
> first, so new papers push older ones to higher offsets. A run that resumes
> from the saved offset keeps working backwards through older papers and does
> not revisit the new ones. To pick those up, pass `start_index=0`: processed
> records are skipped by id, so a rescan costs listing requests (each preceded
> by the extractor's `sleep_before_search` delay) but reprocesses nothing.

| Situation | Behavior |
|-----------|----------|
| Listing request still fails after retries | `run()` raises `PipelineAborted` (cause: `UpstreamError`) |
| Source rejects the listing request, e.g. arXiv answers `400` | `run()` raises `PipelineAborted` (cause: `ExtractionError`) |
| Listing payload can't be parsed | `run()` raises `PipelineAborted` (cause: `MalformedResponseError`) |
| Listing is valid but has no entries | `run()` returns the count normally |
| Listing page holds only already-processed records | paging continues with the next page |
| One record raises, e.g. a transient full-text failure | logged through `logger`; record left unmarked; saved offset held at its page; other records continue |
| Records on one page fail and none on it is processed, but a later page processes a record | paging continues; the failed records stay unmarked for the next run |
| Records fail with none processed on a second page before any progress, or on the last page of the listing, e.g. a rejected API key or an unreadable CSV | `run()` raises `PipelineAborted` (cause: the last record's error) |
| arXiv reports the LaTeX and PDF as unavailable (e.g. 404), or neither can be parsed | full text falls back to the abstract |
| arXiv serves a single gzipped `.tex` file or a PDF as the e-print | the TeX is read, or the PDF is used instead |
| LLM call fails inside `AsyncLLMRelevanceFilter`, or its verdict is unclear | returns `default_on_error` (**`True`**) |
| Record has an empty abstract | relevance filters return `default_on_empty_abstract` (**`True`**) |
| LLM call fails inside `AsyncLLMEntityExtractor`, or its entity list is malformed | `LLMError` propagates: logged, record left unmarked and retried on the next run |
| Record has a missing or blank `record_id` | skipped and logged, since it can't be tracked as processed |

All library exceptions derive from `SciEtlError`: `ExtractionError`
(`UpstreamError`, `MalformedResponseError`), `ParsingError`, `LLMError`,
`EmbeddingError`, `EmbeddingStoreError`, `SearchError` (`SearchQueryError`,
`SearchStoreError`), `ConfigurationError`, and `PipelineAborted`. All of them can be imported from `sci_etl_core`. The bundled
parsers raise `ParsingError` for bytes they can't read; a custom `Parser`
should do the same, so `AsyncArxivExtractor` moves on to its next source
instead of failing the record.

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

## Retries

`AsyncArxivExtractor`, `AsyncOpenAICompatibleClient`, and `AsyncOpenAIEmbedder`
retry throttling (`429`), server errors, and transport faults, making at most
`max_retries` attempts per request (default 3):

- **Backoff.** Between attempts they wait `backoff_factor ** attempt` seconds:
  1 s, then 2 s with the default factor of 2.
- **`Retry-After`.** When a response says how long to wait, in `Retry-After`
  or the `retry-after-ms` header OpenAI-compatible APIs send, they wait that
  long instead whenever it is longer than the backoff, up to `max_retry_after`
  seconds (default 60).
- **One retry layer.** The OpenAI SDK's own retries are turned off, so
  `max_retries` is the total number of attempts.
- **Visibility.** The arXiv extractor logs each retry and its wait through
  `logger`.

The client from `build_async_client` also retries failed connections at the
transport level (`total_retries`, default 5) before the extractor counts one
failed attempt.

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
`logging.Logger` that writes to a file and to stdout, creating the file's
folder if it doesn't exist. Calling it again with the same name, file, and
level returns the same logger; a different file or level replaces the handlers
it installed. Components take a plain `logger` callable, so pass a bound
method:

```python
from sci_etl_core import configure_logging

log = configure_logging("my_pipeline", "pipeline.log")
# AsyncETLPipeline(..., logger=log.warning)
# AsyncArxivExtractor(..., logger=log.info)
```

## Token Usage

`AsyncOpenAICompatibleClient.usage` and `AsyncOpenAIEmbedder.usage` return a
`TokenUsage` snapshot counted across every response the client has received,
including responses whose body was then rejected:

```python
async with pipeline:
    await pipeline.run(query="all:galaxy", total_limit=50)
usage = llm.usage
print(f"{usage.requests} requests, {usage.prompt_tokens} prompt and {usage.completion_tokens} completion tokens")
```

`TokenUsage` has `requests`, `prompt_tokens`, `completion_tokens`, and
`total_tokens`. A response without usage data counts as a request with zero
tokens. Other `AsyncLLMClient` and `AsyncEmbedder` implementations return
`None` unless they override the `usage` property.

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
                                                  +--> MemoryIngestor (optional)
                                                  |      AsyncChunkIngestor: TextChunker -> AsyncEmbedder
                                                  |        -> AsyncEmbeddingStore
                                                  |      AsyncSearchIndexer: AsyncTextSearchStore
                                                  |      AsyncCompositeIngestor: several at once
                                                  v
                          AsyncEntityExtractor.extract
                                                  |
                                                  v
                          AsyncExporter.export(entities, destination) --> mark processed

After each page: AsyncStateManager.save_metadata(last_start_index)

Search:    AsyncHybridSearcher.search(query) --> AsyncTextSearchStore.search (BM25) -------+--> fusion --> SearchOutcome
                                             --> AsyncSimilarArticleFinder (vector memory) -+
Discovery: build_discovery_graph(seed) --> AsyncEdgeSource.neighbours --> DiscoveryGraph --> filter_graph
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
| Memory ingest | `MemoryIngestor` | `AsyncChunkIngestor`, `AsyncSearchIndexer`, `AsyncCompositeIngestor` | `sci_etl_core.embeddings`, `sci_etl_core.search`, `sci_etl_core` |
| Text search | `AsyncTextSearchStore` | `InMemoryTextSearchStore`, `AsyncSqliteFts5Store` | `sci_etl_core.search` |
| Fusion | `FusionStrategy` | `reciprocal_rank_fusion`, `normalized_score_fusion`; `AsyncHybridSearcher` | `sci_etl_core.search` |
| Discovery graph | `AsyncEdgeSource` | `EmbeddingEdgeSource`, `MetadataEdgeSource`; `build_discovery_graph`, `filter_graph` | `sci_etl_core.search` |
| Post-processing | `Processor`, `RecordValidator` | `ProcessorChain`, `NormalizationStep`, `DeduplicationStep`, `ClusteringStep`, `CompletenessStep`, `QualityFlagStep`; `NumericRangeValidator`, `KeywordExclusionValidator`, `CompositeValidator` | `sci_etl_core.processors` |
| Sync adapters | `Extractor`, `RelevanceFilter`, `EntityExtractor`, `LLMClient`, `Exporter`, `StateManager` | `Sync*Adapter` for each | `sci_etl_core` |
| Orchestration | — | `AsyncETLPipeline`, `ETLPipeline` | `sci_etl_core` |

The pipelines, stage interfaces, adapters, and most implementations are also
re-exported from `sci_etl_core` itself; parser implementations, processor
steps, and validators come from their subpackages. Supporting modules:
`sci_etl_core.config`, `sci_etl_core.http_async` (`build_async_client`),
`sci_etl_core.rate_limiter`, `sci_etl_core.signals`, `sci_etl_core.log_utils`,
`sci_etl_core.exceptions`, and `sci_etl_core.discovery` (the read-model for
user interfaces). Every package loads its public names on first
access, so importing one component never requires another component's
optional dependencies.

## Testing

```bash
pip install -e ".[full,dev,lint]"
pytest                                                # full suite
pytest --cov=sci_etl_core --cov-report=term-missing   # with coverage
ruff check .                                          # lint and import order
mypy                                                  # type check the source
```

The suite runs offline: HTTP, LLM, and embedding calls are mocked, and a stub
replaces SQLAlchemy when it isn't installed. Hypothesis property tests and ABC
conformance tests guard the public interfaces, and `pytest --cov` fails if line
coverage drops below 100%.

ruff and mypy run in CI alongside the test suite; the `lint` extra installs
both locally, and `ruff check --fix .` applies the safe fixes. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## Contributing

Contributions are welcome — new extractors, parsers, exporters, and embedding
backends especially. See [CONTRIBUTING.md](CONTRIBUTING.md) to get set up, and
browse [good first issues](.github/ISSUE_TEMPLATE/good_first_issue.md) if
you're new. Moving an existing pipeline onto the library? See [MIGRATION.md](MIGRATION.md).
All participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

Released under the MIT License. See [LICENSE](LICENSE) for details.
