# Roadmap

This roadmap communicates direction, not commitments — timelines and priorities
shift with community feedback. Want to help with any item? Comment on the
matching issue or open one. Items marked **good first issue** are approachable
for newcomers.

## Current Status — v0.1.x

`sci-etl-core` is functional and used in production for scientific corpus ETL,
including [udg-catalogue](https://github.com/xueromll/udg-catalogue).

**Shipped**

- **Async-first core.** Every component is an async implementation;
  `ETLPipeline` is a single blocking entrypoint running on a background event
  loop.
- **Pluggable ABCs** for extraction, parsing, LLM relevance filtering and
  entity extraction, export, state, embeddings, chunking, vector storage, and
  dataframe processing.
- **`AsyncETLPipeline` orchestrator** with bounded per-record concurrency, plus
  `ProcessorChain` for post-processing.
- **Explicit failure signaling** with `UpstreamError`,
  `MalformedResponseError`, and `PipelineAborted` (which carries the partial
  count).
- **Crash-safe persistence.** Atomic CSV and metadata writes, OS-level file
  locking, plain-file and SQLite state backends, and a `flush()` hook.
- **Resumable paging.** Runs resume from the saved listing offset, move past
  pages of already-processed records, and accept `start_index=` to rescan.
- **Semantic memory.**
  - Embedders: OpenAI-compatible and local sentence-transformers.
  - Chunking: sliding-window chunker.
  - Stores: in-memory and SQLite vector stores.
  - Search and filtering: similar-article search and an embedding-based
    relevance filter.
- **Concrete implementations.** arXiv extractor; OpenAI-compatible LLM client;
  PDF / LaTeX / HTML parsers; CSV upsert, SQL table, and 3D Plotly exporters;
  processor steps for normalization, deduplication with pluggable neighbor
  matching, DBSCAN clustering, completeness, and quality flags; record
  validators.
- **Standalone primitives.** Rate limiters (`Null` / `Semaphore` /
  `AioLimiter`) and `ShutdownSignal` for SIGINT/SIGTERM handling.
- **Synchronous component adapters** (`Sync*Adapter`) for plugging blocking
  implementations into either pipeline.
- **Per-component installs.** Packages load optional dependencies on first
  use, with an extra for each component group.
- **Typed configuration** from YAML + `.env`, with `SecretStr` secrets.
- **Offline test suite.** pytest, Hypothesis property tests, ABC conformance
  tests; 100% line coverage, enforced by `pytest --cov`.
- **Continuous integration.** The suite and its coverage gate run on every
  push and pull request, on Linux, Windows, and macOS with Python 3.10–3.14.
  CI also builds the sdist and wheel, checks their metadata, and imports the
  wheel in a clean environment.
- **Migration guide.** [MIGRATION.md](MIGRATION.md) walks through moving
  udg-catalogue onto the library, including parity checks against the old
  code.

## Next Up — v0.2

### Reliability

- **Graceful shutdown built in.** Wire `ShutdownSignal` and
  `AsyncStateManager.flush()` into `AsyncETLPipeline`, so an interrupt drains
  in-flight work without user-side task management. It should also work
  through `ETLPipeline`, whose background event loop can't install signal
  handlers today.
- **Incremental resume for shifting listings.** Pick up new submissions in a
  newest-first listing without rescanning from offset 0, for example by
  tracking the newest submission already seen. udg-catalogue rescans from 0
  on every run, paying a listing request and the search delay for every page
  it has already seen.
- **`Retry-After`-aware backoff.** Honor `Retry-After` on `429` and `503`
  responses in the arXiv extractor and in the LLM and embedding clients. The
  default backoff waits 1 s and then 2 s, which is shorter than arXiv's
  throttling: udg-catalogue's live run got `429` on every listing attempt,
  which led it to raise `backoff_factor` to 5.
- **Rate-limiter injection.** Accept an `AsyncRateLimiter` in extractors and in
  LLM and embedding clients, with per-host limits and limiters shared across
  components, replacing the wrapper class the README currently shows.

### Found in the udg-catalogue migration

Each of these is code udg-catalogue still carries on top of the library (see
[MIGRATION.md](MIGRATION.md)).

- **Record validation in the pipeline.** Accept a `RecordValidator` on
  `AsyncLLMEntityExtractor`, logging what it rejects, so projects no longer
  need a wrapper extractor to drop invalid entities before export.
- **Config-driven components.** Let `HttpConfig`, `RateLimitConfig`, and
  `PipelineConfig` configure components directly, instead of being copied into
  constructors by hand. Align `PipelineConfig` with `run()` at the same time:
  add `page_size` and a search delay, which udg-catalogue adds by subclassing,
  and reconcile `max_records` and `max_workers` with `total_limit` and
  `max_concurrency`.
- **Richer 3D plots.** Let `ScatterPlotConfig` take hover data, a hover
  template, a continuous color scale, and a fixed color range, so
  `AsyncPlotly3DExporter` can replace project-specific Plotly figures.
- **More processor steps.** A `ValueClipStep` that clamps numeric columns
  during post-processing, as the CSV exporter's `numeric_clip` does during
  export, and a step that sorts rows and orders columns.
  *(good first issue: `ValueClipStep`)*

### New capabilities

- **LLM response caching.** Pluggable cache (in-memory + on-disk) keyed on
  prompt and model, to cut cost and speed up re-runs. Injected like every other
  collaborator, so custom backends (e.g. Redis) are simple to add.
  *(good first issue: in-memory backend)*
- **New extractors.** PubMed, Semantic Scholar, and OpenAlex, all behind the
  existing `AsyncExtractor` interface. *(good first issue: pick one source)*
- **New parsers.** DOCX and structured JATS/XML parsing.
- **Pipeline observability.** Structured, per-record progress events and simple
  run metrics (counts, durations, failures), beyond the current `logger`
  callback. Include LLM token usage, which `AsyncOpenAICompatibleClient`
  currently discards, so a run's API cost can be reported.

### Project health

- **Lint and type checks in CI.** Configure ruff and mypy and run both on every
  pull request. The package ships `py.typed`, but nothing checks its
  annotations yet. *(good first issue)*
- **Releases on PyPI.** The README's install commands assume a PyPI package,
  but `sci-etl-core` isn't published yet, so projects vendor a wheel or pin a
  Git tag. Add a tag-triggered release workflow with trusted publishing, and a
  changelog.
- **Retire the `requests` session helper.** `sci_etl_core.http.build_retrying_session`
  is a synchronous leftover that no component uses. Deprecate it, and drop
  `requests` from the `full` extra once it's removed.

## Later — v0.3+

- **Targeted reprocessing.** Let state managers forget selected record ids, so
  records can be re-extracted after a prompt or normalizer fix without
  archiving all state and rescanning everything.
- **Typed entity schemas.** Let `AsyncLLMEntityExtractor` take a Pydantic
  model: request JSON-schema structured output where the provider supports it,
  and validate each entity's fields before export.
- **Additional exporters.** Parquet, JSONL, and a pluggable object-store
  target, plus record-level SQL and JSONL exporters that accept the pipeline's
  `list[dict]` output. `AsyncSqlTableExporter` only takes a DataFrame today.
- **Cascading relevance filters.** Put a cheap embedding filter in front of the
  LLM filter, so records it rejects never cost an LLM call.
- **Streaming pipeline mode.** Yield records as they complete instead of
  running page-by-page to completion.
- **Config-driven assembly.** Build a full pipeline from a single declarative
  config file, no wiring code required.
- **Checkpoint/resume for processors.** Persist intermediate dataframes to
  resume long post-processing chains.
- **Scalable vector memory.** An approximate-nearest-neighbor
  `AsyncEmbeddingStore` for corpora larger than the exact linear-scan SQLite
  store handles comfortably.

## Future Ideas (Exploratory)

- Chat-completion backends beyond OpenAI-compatible APIs (local models, other
  providers). Local *embeddings* already ship via sentence-transformers.
- A small CLI (`sci-etl run config.yaml`) wrapping the config-driven assembly.
- Optional distributed execution for very large corpora.
- A documentation site with an API reference generated from the docstrings.

---

Have an idea that isn't here? Open a
[feature request](.github/ISSUE_TEMPLATE/feature_request.md) — the roadmap is
shaped by real use cases.
