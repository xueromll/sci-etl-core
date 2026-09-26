# Roadmap

This roadmap states direction, not commitments. Priorities follow real use
cases, and every item must fit the library's scope: scientific papers in,
structured and searchable data out. An item that does not fit is declined,
however useful it would be elsewhere. To work on an item, comment on its issue
or open one. Items marked **good first issue** suit newcomers.

Each milestone lists its exit criteria. A milestone ships when every criterion
holds with the test suite offline and line coverage at 100%.

## Current release — v0.5.1

[CHANGELOG.md](CHANGELOG.md) lists every change by release, and
[MIGRATION.md](MIGRATION.md) explains how to upgrade from 0.4 and what 0.5.1
changes.

| Consumer | Requires | Runs |
|----------|----------|------|
| [udg-catalogue](https://github.com/xueromll/udg-catalogue) | `sci-etl-core>=0.4.0,<0.5` in its latest commit, with the `embeddings`, `embeddings-local`, and `search` extras; its next commit requires `>=0.5.1,<0.6` | 0.4 in production, including search, discovery, and embeddings |
| [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) | `>=0.5.0.dev0,<0.6` on `master`, and its suite passes against core `master`; its next release, 0.3.0, requires `>=0.5.1,<0.6` | 0.2, in its latest release 0.2.1 |

| Area | Shipped |
|------|---------|
| Orchestration | `AsyncETLPipeline` with bounded per-record concurrency, exact `total_limit`, stall detection, and `PipelineAborted` carrying partial counts; `ETLPipeline` as the blocking facade on a background event loop |
| Contracts | ABCs for extractors, relevance filters, entity extractors, LLM clients, exporters, state managers, parsers, embedders, chunkers, vector and text stores, processors, and validators; `Sync*Adapter` wrappers for blocking implementations, deprecated until their removal in 0.6.0 |
| Reliability | Graceful shutdown through `ShutdownSignal`, state flushed however a run ends, atomic writes and OS file locks, `Retry-After`-aware retries, shared and per-host rate limiters |
| Resumption | Saved listing cursors that advance only past settled pages, result caps reported as truncated with the next run starting from the first page, a quarantine for records that keep failing, schema-versioned state that upgrades files written by 0.4, and `newest_first` runs that pick up new submissions without rescanning |
| Sources | arXiv, PubMed, Semantic Scholar, and OpenAlex extractors; PDF, LaTeX, HTML, DOCX, and JATS XML parsers |
| LLM | OpenAI-compatible chat and embedding clients with token usage, response caching in memory or SQLite, entity validation in the extractor |
| Memory and search | Vector memory, Boolean query language with `NEAR`, SQLite FTS5 and in-memory text stores, hybrid rank fusion, range and metadata filters, facets, snippets, discovery graphs, and backfill from vector memory |
| Configuration | Pydantic models loaded from YAML and `.env`, `SecretStr` keys, secret-safe validation errors, `from_config` builders |
| Observability | Progress events and `RunMetrics` with counts, durations, outcome, and token usage |
| Project health | Offline pytest and Hypothesis suite at 100% line coverage, with branch coverage reported; ruff with the `ASYNC`, `UP`, `RUF`, and `PT` rule sets, and mypy with stricter flags on the core contracts; CI on Linux, Windows, and macOS for Python 3.11–3.14, PyPI trusted publishing, a documentation site with a generated API reference |
| Guardrails | A committed snapshot of every stable signature, which also covers every name a known consumer uses; the guarantees of `AsyncETLPipeline.run` numbered in a run-semantics guide, each with a named test; the sci-etl-cli suite run against every core change; nightly smoke tests against each bundled source; a throughput benchmark that runs every exporter through the pipeline |

Still open: a sci-etl-cli release and a udg-catalogue commit that require core
0.5.1, and a live check of how long OpenAlex cursors stay valid.
PubMed and Semantic Scholar keep offset paging and report their caps as
truncated: E-utilities serves at most 9,999 results even through its history
server, and Semantic Scholar's bulk search returns fixed pages of 1,000
papers, which cannot honor `page_size`.

## Path to 1.0

Each public contract changes at most once more before 1.0. The run contract
(extractor, state, constructor) breaks in 0.5.0, the data contract (entities,
exporter, logging, dependencies) in 0.6.0, and every later release is
additive. A release is tagged only when sci-etl-cli passes against it and
udg-catalogue completes a run on it. Each breaking change gets a
[MIGRATION.md](MIGRATION.md) entry.

## v0.6.0 — Data contract and claims

Breaking, for the last time before 1.0.

- **Typed entity schemas.** `AsyncLLMEntityExtractor(schema=...)` requests
  JSON-schema structured output where the provider supports it, validates
  every entity, and adds the schema to the LLM cache key.
- **Exporter lifecycle.** Exporters receive each record with its entities
  through `open`, `write`, `flush`, and `aclose`, with at-least-once delivery.
  New JSONL and CSV exporters write in time linear in the number of records.
- **Claims and provenance.** A `sci_etl_core.claims` package, provisional at
  first, records each extracted value with its paper, its evidence sentence,
  and the model, prompt, and schema that produced it, and keeps rejected
  entities, with reasons, for review.
- **Standard logging.** Modules log through `logging.getLogger(__name__)`.
- **Lighter install.** The base install requires only `pydantic`; parsers,
  loaders, and processors move to extras. `load_config` no longer loads `.env`
  implicitly.
- **udg-catalogue guide.** A guide page follows udg-catalogue end to end,
  from an arXiv query to a catalog and a search over its papers. The docs
  landing page then links to it instead of the udg-catalogue repository.

Exit criteria: no delivery test loses a record, a bare install imports every
stable name, and both consumers run on 0.6.0 without `DeprecationWarning`.

## v0.7.0 — Additive features and the testing kit

No breaking change and no new deprecation.

- **Targeted reprocessing.** An optional `forget(record_ids)` contract, which
  both bundled state managers implement, lets records be re-extracted without
  discarding all state.
- **Cascading relevance filters.** A composite filter runs a cheap filter,
  such as `AsyncEmbeddingRelevanceFilter`, before the LLM filter.
- **Testing kit.** `sci_etl_core.testing` provides contract suites that
  third-party extractors, state managers, exporters, and embedding stores can
  run.

## v1.0.0 — Stabilization

1.0.0 guarantees three tiers: stable names follow Semantic Versioning,
provisional names may change in a minor release with a changelog entry, and
private names may change at any time. Every name a known consumer imports is
stable. The release candidate is tagged once one full minor has shipped with
no breaking change, the public-surface snapshot and run-semantics tests gate
every change, and files written by 0.6.0 and 0.7.0 open in it.

## Later

These items wait on a consumer that needs them, or on a measurement.

- **Knowledge synthesis (sci-etl-kg).** Unit normalization, consolidation of
  repeated measurements, and pooled effect sizes built on the 0.6.0 claims, in a
  separate package that builds on 1.0.0. Until the start rule below holds,
  this work stays in udg-catalogue, because a layer built from one catalog
  would bake in that catalog's assumptions. The core never imports
  sci-etl-kg, so no outcome below affects core users.
    - **Second catalog.** Once 1.0.0 is out and a second consumer that builds
      a catalog needs unit normalization or consolidation, sci-etl-kg 0.1
      starts with those two features only, built on stable names.
    - **No second catalog.** If no second catalog exists by September 2027,
      sci-etl-kg moves to Not planned until one appears.
    - **Six months idle.** If sci-etl-kg goes six months without a release,
      or its upkeep delays a core release, its last 0.x release is frozen,
      marked unmaintained, and archived.
    - **Contradiction detection.** Contradiction detection and causal graphs
      stay out of every release plan; notebooks and research branches are
      the limit.
- **Scalable vector memory.** An approximate-nearest-neighbor
  `AsyncEmbeddingStore` for corpora the exact-scan SQLite store cannot serve
  interactively. Starts once a corpus defines the target size and latency.
- **Candidate pool tuning.** Measure how many distinct records the top chunks
  span on a real memory database, such as udg-catalogue's, and set the
  `chunk_pool_factor` default from the measurement.
- **Columnar export.** A Parquet sink for post-processed tables, behind an
  optional extra.
- **Single-pass PDF parsing.** `PdfPlumberParser.extract_text` opens every PDF
  twice, once for text and once for tables. Read both in one pass.
- **Citation edges.** An edge source for co-citation and bibliographic
  coupling, built on the reference lists `AsyncOpenAlexExtractor` stores under
  `metadata["references"]`.
- **Substring and CJK matching.** An optional trigram text index, which
  roughly doubles index size.
- **Discovery interface.** An interactive search and graph view on the
  `sci_etl_core.discovery` read-model, built outside this repository as a
  sci-etl-cli subcommand or a separate application.

## Exploratory

- **Native provider clients.** Local servers such as vLLM, llama.cpp, and
  Ollama already work through the OpenAI-compatible client. A native client
  is worth adding only for a provider without an OpenAI-compatible endpoint,
  or one whose structured-output support that endpoint lacks.

## Not planned

These were considered and withdrawn; some appeared on earlier roadmaps.

- **Blocking orchestration contracts.** The asynchronous API is the supported
  one. Blocking leaf components, such as parsers and pandas processors, stay
  blocking; the blocking extractor, state, exporter, LLM, relevance, and
  entity contracts, their adapters, and the fixes to the bridge beneath them
  are withdrawn in favor of their asynchronous counterparts.

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
- **Renaming `sci-etl-core` or `sci_etl_core`.** The distribution and import
  names stay as they are. A rename would need a bridge release and a
  migration in every consumer, and would change nothing about what the
  library does.
- **A `sci-etl` meta-package.** sci-etl-cli already depends on the core with
  the extras it needs, so a meta-package would only add a release to every
  release.
- **Republishing `sci-etl-cli` as `sci-etl`.** The CLI already ships on PyPI
  as sci-etl-cli and installs the `sci-etl` command. A new distribution name
  would be another rename, with its own bridge release.

---

Have a use case the roadmap does not cover? Open a
[feature request](.github/ISSUE_TEMPLATE/feature_request.md).
