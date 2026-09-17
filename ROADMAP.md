# Roadmap

This roadmap states direction, not commitments. Priorities follow real use
cases. To work on an item, comment on its issue or open one. Items marked
**good first issue** suit newcomers.

Each milestone lists its exit criteria. A milestone ships when every criterion
holds with the test suite offline and line coverage at 100%.

## Current release — v0.4.0

`sci-etl-core` runs scientific corpus ETL in production, including
[udg-catalogue](https://github.com/xueromll/udg-catalogue).
[CHANGELOG.md](CHANGELOG.md) lists every change by release.

| Area | Shipped |
|------|---------|
| Orchestration | `AsyncETLPipeline` with bounded per-record concurrency, exact `total_limit`, stall detection, and `PipelineAborted` carrying partial counts; `ETLPipeline` as the blocking facade on a background event loop |
| Contracts | ABCs for extractors, relevance filters, entity extractors, LLM clients, exporters, state managers, parsers, embedders, chunkers, vector and text stores, processors, and validators; `Sync*Adapter` wrappers for blocking implementations |
| Reliability | Graceful shutdown through `ShutdownSignal`, state flushed however a run ends, atomic writes and OS file locks, `Retry-After`-aware retries, shared and per-host rate limiters |
| Resumption | Saved listing offsets that advance only past settled pages, and `newest_first` runs that pick up new submissions without rescanning |
| Sources | arXiv, PubMed, Semantic Scholar, and OpenAlex extractors; PDF, LaTeX, HTML, DOCX, and JATS XML parsers |
| LLM | OpenAI-compatible chat and embedding clients with token usage, response caching in memory or SQLite, entity validation in the extractor |
| Memory and search | Vector memory, Boolean query language with `NEAR`, SQLite FTS5 and in-memory text stores, hybrid rank fusion, range and metadata filters, facets, snippets, discovery graphs, and backfill from vector memory |
| Configuration | Pydantic models loaded from YAML and `.env`, `SecretStr` keys, secret-safe validation errors, `from_config` builders |
| Observability | Progress events and `RunMetrics` with counts, durations, outcome, and token usage |
| Project health | Offline pytest and Hypothesis suite at 100% line coverage, ruff and mypy, CI on Linux, Windows, and macOS for Python 3.10–3.14, PyPI trusted publishing, a documentation site with a generated API reference |

## v0.4.x — Integration fixes

No API change. These items unblock
[sci-etl-cli](https://github.com/xueromll/sci-etl-cli), which lives in its own
repository.

- **sci-etl-cli on core 0.4.** The CLI requires `sci-etl-core<0.4`. Against
  0.4 it reads the deprecated `max_records` and `max_workers` properties,
  which ignore `run --limit` and `run --workers` overrides applied through
  `model_copy`. The CLI moves to `total_limit` and `max_concurrency`, requires
  `>=0.4,<0.5`, and renames the keys in its `init` template.
- **Cross-repository CI.** Run the CLI suite against sci-etl-core `master` on
  every core push, so an API change that breaks the CLI fails before release.
- **Accurate defaults.** `HttpConfig.user_agent` and `build_async_client`
  default to `sci-etl-core/0.1`; derive the version from the installed
  package. **good first issue**

Exit criteria: `pip install sci-etl-cli` resolves to sci-etl-core 0.4, and the
CLI suite passes against core `master` without `DeprecationWarning`.

## v0.5.0 — API hardening

The release that removes what 0.4 deprecated. Each breaking change gets a
[MIGRATION.md](MIGRATION.md) entry.

### Removals announced in 0.4

- `PipelineConfig.max_records` and `max_workers`, their YAML keys, and
  `run(max_records=)`.
- `sci_etl_core.http.build_retrying_session`, and `requests` in the `full`
  extra and `types-requests` in the `lint` extra.

### Typed seams

- **Typed facades.** `ETLPipeline.__init__` and `run` accept `*args` and
  `**kwargs`, and `from_config` accepts `**Any`, so mypy cannot check
  collaborators passed through them. Give them the explicit signatures of
  `AsyncETLPipeline`.
- **Strict config sections.** Nested sections ignore unknown keys, so a typo
  such as `search.bm25.titel` is silently dropped even when the root model
  forbids extras. Forbid unknown keys in every bundled section, with an
  opt-out on `BaseAppConfig` subclasses.
- **Exporter shape.** `AsyncExporter.export(data: Any, ...)` hides that the
  pipeline passes `list[dict[str, Any]]`, and `AsyncSqlTableExporter` accepts
  only a `DataFrame`. Make the exporter contract generic over its input type
  and give the pipeline an exporter typed for entity lists.
- **Contract parity.** Add `flush` to the blocking `StateManager` and forward
  it from `SyncStateManagerAdapter`, and add an `AsyncParser` contract that
  `AsyncPdfPlumberParser` implements.

### Async core

- **Non-blocking sync adapters.** `SyncExtractorAdapter.search` runs a
  blocking listing request on the event loop, which delays a shutdown request
  until the request returns. Run it in a worker thread; listing calls are
  already sequential, so ordering is unchanged.
- **Bridge re-entrancy.** `run_sync` called from the bridge loop's own thread,
  for example by a blocking component that calls back into a facade, waits on
  itself until the call timeout. Detect that case and raise `RuntimeError`.
- **Bridge teardown.** On interpreter exit, cancel pending bridge tasks before
  stopping the loop, and skip `loop.close()` when the thread did not stop
  within the timeout.
- **Single-pass PDF parsing.** `PdfPlumberParser.extract_text` opens every PDF
  twice, once for text and once for tables. Read both in one pass.

### Features

- **Targeted reprocessing.** A `forget(record_ids)` operation on both bundled
  state managers, exposed as a separate optional contract so third-party
  state managers keep working, lets records be re-extracted after a prompt or
  normalizer fix without discarding all state.
- **Cascading relevance filters.** A composite filter that runs a cheap
  filter, such as `AsyncEmbeddingRelevanceFilter`, before the LLM filter, so
  a rejected record never costs an LLM call.
- **Record-level exporters.** JSONL and SQL exporters that accept the
  pipeline's entity lists and reuse one connection for the whole run.

Exit criteria: mypy passes on a pipeline built through `ETLPipeline` with no
`Any` at its seams, every deprecated name is gone, and MIGRATION.md covers
each removal.

## v0.6.0 — Structured extraction

- **Typed entity schemas.** Let `AsyncLLMEntityExtractor` take a Pydantic
  model: request JSON-schema structured output where the provider supports
  it, fall back to JSON mode elsewhere, and validate every entity before
  export. The schema becomes part of the LLM cache key, so changing it never
  serves stale cached responses.
- **Columnar export.** A Parquet exporter for post-processed tables, behind a
  new optional extra.
- **Candidate pool tuning.** Measure how many distinct records the top chunks
  span on a real memory database, such as udg-catalogue's, and set the
  `chunk_pool_factor` default from the measurement. The benchmark script
  ships with the repository.

Exit criteria: an extraction run with a schema exports only entities that
validate against it, on providers with and without structured output.

## Later

These items depend on measurements or on the milestones above.

- **Scalable vector memory.** An approximate-nearest-neighbor
  `AsyncEmbeddingStore` for corpora the exact-scan SQLite store cannot serve
  interactively. Discovery graphs run one vector query per node, so they
  speed up with no change to the graph layer. Starts once the candidate pool
  benchmark defines the target corpus size and latency.
- **Citation edges.** An edge source for co-citation and bibliographic
  coupling, built on the reference lists `AsyncOpenAlexExtractor` stores under
  `metadata["references"]`.
- **Substring and CJK matching.** An optional trigram text index, which
  roughly doubles index size. Starts when a corpus needs it.
- **Discovery interface.** An interactive search and graph view on the
  `sci_etl_core.discovery` read-model, built outside this repository as a
  sci-etl-cli subcommand or a separate application.

## Exploratory

- **Native provider clients.** Local servers such as vLLM, llama.cpp, and
  Ollama already work through the OpenAI-compatible client. A native client
  is worth adding only for a provider without an OpenAI-compatible endpoint,
  or one whose structured-output support that endpoint lacks.

## Not planned

These appeared on earlier roadmaps and were withdrawn.

- **Config-driven assembly in the library.** sci-etl-cli already builds a
  complete pipeline from one YAML file. The library supplies `from_config`
  builders; declarative assembly stays in the CLI, so the core carries no
  component registry.
- **Streaming pipeline mode.** `on_event` already reports every record as it
  finishes. Yielding records ahead of page settlement would conflict with the
  rule that the saved offset advances only past fully settled pages.
- **Processor checkpoints.** Processor chains are in-memory pandas
  transformations of an exported table, which is already the durable
  checkpoint; rerunning the chain is cheaper than persisting each step.
- **Distributed execution.** State managers rely on local file locks and a
  single SQLite writer. Sharding a corpus across independent runs, each with
  its own state, covers large corpora without a distributed runtime.

---

Have a use case the roadmap does not cover? Open a
[feature request](.github/ISSUE_TEMPLATE/feature_request.md).
