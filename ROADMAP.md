# Roadmap

This roadmap communicates direction, not commitments — timelines and priorities
shift with community feedback. Want to help with any item? Comment on the
matching issue or open one. Items marked **good first issue** are approachable
for newcomers.

## Current Status — v0.1.x

`sci-etl-core` is functional and used in production for scientific corpus ETL.

**Shipped**

- Async core with a generated synchronous facade (single source of truth).
- Six pluggable ABC layers: Extractor, Parser, LLM (client / relevance / entity),
  Processor, Exporter, State Manager.
- `ETLPipeline` / `AsyncETLPipeline` orchestrators and `ProcessorChain`.
- Concrete implementations: arXiv extractor; OpenAI-compatible LLM client;
  PDF / LaTeX / HTML parsers; CSV upsert, SQL table, and 3D Plotly exporters;
  file-based state manager.
- Pluggable rate limiting (`Null` / `Semaphore` / `AioLimiter`).
- Typed YAML + `.env` configuration with `SecretStr` secrets.
- Offline-first test suite: pytest, Hypothesis property tests, ABC conformance
  tests, 100% coverage.

## Next Up — v0.2

- **LLM response caching.** Pluggable cache (in-memory + on-disk) keyed on prompt
  and model, to cut cost and speed up re-runs. Injected like every other
  collaborator so custom backends (e.g. Redis) are trivial. *(good first issue:
  in-memory backend)*
- **Richer rate limiting.** Per-host limits, adaptive backoff informed by
  `Retry-After`, and shared limiter instances across extractors and LLM clients.
- **New extractors.** PubMed, Semantic Scholar, and OpenAlex, all behind the
  existing `AsyncExtractor` interface. *(good first issue: pick one source)*
- **New parsers.** DOCX and structured JATS/XML parsing.
- **Pipeline observability.** Structured, per-record progress events and simple
  run metrics (counts, durations, failures).

## Later — v0.3+

- **Additional exporters.** Parquet, JSONL, and a pluggable object-store target.
- **Streaming pipeline mode.** Yield records as they complete instead of running
  page-by-page to completion.
- **Config-driven assembly.** Build a full pipeline from a single declarative
  config file, no wiring code required.
- **Checkpoint/resume for processors.** Persist intermediate dataframes to
  resume long post-processing chains.

## Future Ideas (Exploratory)

- Alternative LLM backends beyond OpenAI-compatible (local models, other APIs).
- Vector-store exporter for downstream semantic search.
- A small CLI (`sci-etl run config.yaml`) wrapping the config-driven assembly.
- Optional distributed execution for very large corpora.

---

Have an idea that isn't here? Open a
[feature request](.github/ISSUE_TEMPLATE/feature_request.md) — the roadmap is
shaped by real use cases.
