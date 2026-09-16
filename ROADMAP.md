# Roadmap

This roadmap communicates direction, not commitments — timelines and priorities
shift with community feedback. Want to help with any item? Comment on the
matching issue or open one. Items marked **good first issue** are approachable
for newcomers.

## Current Status — v0.4

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
- **Releases on PyPI.** A tag-triggered workflow checks the tag against the
  project version and publishes with trusted publishing, so
  `pip install sci-etl-core` works without vendoring a wheel.
- **`Retry-After`-aware retries.** The arXiv extractor and the OpenAI-compatible
  chat and embedding clients wait as long as a throttled response asks, up to
  `max_retry_after`, and the OpenAI SDK's own retries no longer stack on top.
- **Token usage.** The OpenAI-compatible clients count prompt and completion
  tokens, so a run's API cost can be reported.
- **Secret-safe config errors.** Validation messages name the failing keys
  without echoing their values, so an API key can't leak through them.
- **Lint, type checks, and a changelog.** ruff and mypy run in CI next to the
  test suite, and [CHANGELOG.md](CHANGELOG.md) records each release.
- **Local Boolean search.** A query language with phrases, prefixes, field
  scopes, and `AND` / `OR` / `NOT`, an in-memory and a SQLite FTS5 text index
  that need only the standard library, and indexing from the pipeline next to
  the vector memory.
- **Hybrid search.** Reciprocal rank fusion of BM25 and embedding similarity,
  with metadata filters, facet counts, and a report of retrieval legs that
  failed or had nothing to run.
- **Discovery graphs.** Graphs of related papers around a seed record, from
  embedding similarity and shared metadata, with mutual-nearest-neighbor
  pruning, deterministic communities, filtering without I/O, and a read-model
  for user interfaces. Embedding edges run one exact-scan vector query per
  node, so **Scalable vector memory** (v0.5+) would speed graph building up
  with no change to the graph layer.
- **Command-line tool.** [sci-etl-cli](https://github.com/xueromll/sci-etl-cli)
  runs a pipeline from a YAML file, with plug-ins for domain rules.
- **Migration guide.** [MIGRATION.md](MIGRATION.md) walks through moving
  udg-catalogue onto the library, including parity checks against the old
  code.

## Released — v0.4

### Reliability

- **Graceful shutdown built in.** Wire `ShutdownSignal` and
  `AsyncStateManager.flush()` into `AsyncETLPipeline`, so an interrupt drains
  in-flight work without user-side task management. It should also work
  through `ETLPipeline`, whose background event loop can't install signal
  handlers today. *Shipped in 0.4.*
- **Incremental resume for shifting listings.** Pick up new submissions in a
  newest-first listing without rescanning from offset 0, for example by
  tracking the newest submission already seen. udg-catalogue rescans from 0
  on every run, paying a listing request and the search delay for every page
  it has already seen. *Shipped in 0.4.*
- **Rate-limiter injection.** Accept an `AsyncRateLimiter` in extractors and in
  LLM and embedding clients, with per-host limits and limiters shared across
  components, replacing the wrapper class the rate limiting guide currently shows. *Shipped in 0.4.*

### Found in the udg-catalogue migration

Each of these is code udg-catalogue still carries on top of the library (see
[MIGRATION.md](MIGRATION.md)).

- **Record validation in the pipeline.** Accept a `RecordValidator` on
  `AsyncLLMEntityExtractor`, logging what it rejects, so projects no longer
  need a wrapper extractor to drop invalid entities before export. *Shipped in 0.4.*
- **Config-driven components.** Let `HttpConfig`, `RateLimitConfig`, and
  `PipelineConfig` configure components directly, instead of being copied into
  constructors by hand. Finish aligning `PipelineConfig` with `run()` at the
  same time: `page_size` and `search_delay` are already config fields, but
  `max_records` and `max_workers` still need reconciling with `total_limit`
  and `max_concurrency`. Include the search and discovery parameter
  dataclasses (`BM25Weights`, `FusionParams`, `HybridParams`, `GraphParams`). *Shipped in 0.4.*
- **Richer 3D plots.** Let `ScatterPlotConfig` take hover data, a hover
  template, a continuous color scale, and a fixed color range, so
  `AsyncPlotly3DExporter` can replace project-specific Plotly figures. *Shipped in 0.4.*
- **More processor steps.** A `ValueClipStep` that clamps numeric columns
  during post-processing, as the CSV exporter's `numeric_clip` does during
  export, and a step that sorts rows and orders columns. *Shipped in 0.4.*

### New capabilities

- **LLM response caching.** Pluggable cache (in-memory + on-disk) keyed on
  prompt and model, to cut cost and speed up re-runs. Injected like every other
  collaborator, so custom backends (e.g. Redis) are simple to add. *Shipped in 0.4.*
- **New extractors.** PubMed, Semantic Scholar, and OpenAlex, all behind the
  existing `AsyncExtractor` interface. `AsyncOpenAlexExtractor` stores each
  paper's reference list under `references`, which citation edges in
  discovery graphs could use (see v0.5+). *Shipped in 0.4.*
- **New parsers.** DOCX and structured JATS/XML parsing. *Shipped in 0.4.*
- **Pipeline observability.** Structured, per-record progress events and simple
  run metrics (counts, durations, failures), beyond the current `logger`
  callback. The clients already count token usage; fold it into those
  metrics. *Shipped in 0.4.*

### Local search

- **Proximity queries.** `NEAR("a b", 10)` in the query language. *Shipped in 0.4.*
- **Backfill from vector memory.** Rebuild a text index from the chunk text
  already in an `AsyncSqliteEmbeddingStore`, so existing deployments don't
  have to fetch full texts again. Overlapping chunk windows must be merged
  without repeating words, or BM25 over-counts words at window boundaries. *Shipped in 0.4.*
- **Tune the semantic candidate pool.** Measure how many distinct records the
  top chunks span on a real memory database, such as udg-catalogue's, and
  adjust the `chunk_pool_factor` default of 5 if it is too small. *Not in 0.4;
  still open.*
- **Richer snippets.** Highlights from every matching field instead of the one
  FTS5 picks, and a snippet for hits found only by the semantic leg, which
  needs `find_similar_articles` to return each record's best chunk. *Shipped in 0.4.*
- **Range filters.** Filter and count dates and years by range, not only by
  exact value. *Shipped in 0.4.*
- **Substring and CJK matching.** An optional trigram index, if corpora need
  it. It roughly doubles the index size. *Not in 0.4; still open.*

### Project health

- **Retire the `requests` session helper.** `sci_etl_core.http.build_retrying_session`
  is a synchronous leftover that no component uses. Deprecate it, and drop
  `requests` from the `full` extra once it's removed. *Deprecated in 0.4;
  removal in 0.5.*

## Later — v0.5+

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
- **Citation edges.** An edge source for co-citation and bibliographic
  coupling, now that `AsyncOpenAlexExtractor` supplies reference lists under
  `metadata["references"]` (see **New extractors** in v0.4).
- **Discovery interface.** An interactive search and graph view built on the
  `sci_etl_core.discovery` read-model, outside this repository: either a
  subcommand of [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) or an
  application of its own.

## Future Ideas (Exploratory)

- Chat-completion backends beyond OpenAI-compatible APIs (local models, other
  providers). Local *embeddings* already ship via sentence-transformers.
- Optional distributed execution for very large corpora.
- A documentation site with an API reference generated from the docstrings.

---

Have an idea that isn't here? Open a
[feature request](.github/ISSUE_TEMPLATE/feature_request.md) — the roadmap is
shaped by real use cases.
