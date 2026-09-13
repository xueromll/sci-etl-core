# Roadmap

This roadmap communicates direction, not commitments — timelines and priorities
shift with community feedback. Want to help with any item? Comment on the
matching issue or open one. Items marked **good first issue** are approachable
for newcomers.

## Current Status — v0.1.x

`sci-etl-core` is functional and used in production for scientific corpus ETL.

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
  PDF / LaTeX / HTML parsers; CSV upsert, SQL table, and 3D Plotly exporters.
- **Standalone primitives.** Rate limiters (`Null` / `Semaphore` /
  `AioLimiter`) and `ShutdownSignal` for SIGINT/SIGTERM handling.
- **Synchronous component adapters** (`Sync*Adapter`) for plugging blocking
  implementations into either pipeline.
- **Per-component installs.** Packages load optional dependencies on first
  use, with an extra for each component group.
- **Typed configuration** from YAML + `.env`, with `SecretStr` secrets.
- **Offline test suite.** pytest, Hypothesis property tests, ABC conformance
  tests; 100% line coverage, enforced by `pytest --cov`.

## Next Up — v0.2

- **Continuous integration.** Run the test suite and its 100% coverage gate on
  every pull request. *(good first issue)*
- **Incremental resume for shifting listings.** Pick up new submissions in a
  newest-first listing without rescanning from offset 0, for example by
  tracking the newest submission already seen.
- **Graceful shutdown built in.** Wire `ShutdownSignal` and
  `AsyncStateManager.flush()` into `AsyncETLPipeline`, so an interrupt drains
  in-flight work without user-side task management.
- **Config-driven components.** Let `HttpConfig`, `RateLimitConfig`, and
  `PipelineConfig` configure components directly, instead of being copied into
  constructors by hand.
- **Richer rate limiting.** Limiter injection for extractors and LLM/embedding
  clients, per-host limits, adaptive backoff informed by `Retry-After`, and
  shared limiter instances.
- **LLM response caching.** Pluggable cache (in-memory + on-disk) keyed on
  prompt and model, to cut cost and speed up re-runs. Injected like every other
  collaborator, so custom backends (e.g. Redis) are simple to add.
  *(good first issue: in-memory backend)*
- **New extractors.** PubMed, Semantic Scholar, and OpenAlex, all behind the
  existing `AsyncExtractor` interface. *(good first issue: pick one source)*
- **New parsers.** DOCX and structured JATS/XML parsing.
- **Pipeline observability.** Structured, per-record progress events and simple
  run metrics (counts, durations, failures), beyond the current `logger`
  callback.

## Later — v0.3+

- **Additional exporters.** Parquet, JSONL, and a pluggable object-store
  target.
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

---

Have an idea that isn't here? Open a
[feature request](.github/ISSUE_TEMPLATE/feature_request.md) — the roadmap is
shaped by real use cases.
