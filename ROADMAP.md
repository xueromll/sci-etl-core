# Roadmap

This roadmap states direction, not commitments. Priorities follow real use
cases. To work on an item, comment on its issue or open one. Items marked
**good first issue** suit newcomers.

Each milestone lists its exit criteria. A milestone ships when every criterion
holds with the test suite offline and line coverage at 100%.

## Current release — v0.4.1

[CHANGELOG.md](CHANGELOG.md) lists every change by release.

| Consumer | Requires | Runs |
|----------|----------|------|
| [udg-catalogue](https://github.com/xueromll/udg-catalogue) | `sci-etl-core>=0.4.0,<0.5`, with the `embeddings`, `embeddings-local`, and `search` extras | 0.4 in production, including search, discovery, and embeddings |
| [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) | 0.2 or 0.3 in its latest release; its next release requires `>=0.4,<0.5`, and its suite passes against core `master` | 0.3 |

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
| Project health | Offline pytest and Hypothesis suite at 100% line coverage, with branch coverage reported; ruff with the `ASYNC`, `UP`, `RUF`, and `PT` rule sets, and mypy with stricter flags on the core contracts; CI on Linux, Windows, and macOS for Python 3.10–3.14, PyPI trusted publishing, a documentation site with a generated API reference |
| Guardrails | A committed snapshot of every stable signature, which also covers every name a known consumer uses; the guarantees of `AsyncETLPipeline.run` numbered in a run-semantics guide, each with a named test; the sci-etl-cli suite run against every core change; nightly smoke tests against each bundled source; a throughput benchmark that runs every exporter through the pipeline |

Still open from 0.4.1: a sci-etl-cli release that requires core 0.4, and a udg-catalogue run on 0.4.1.

## Path to 1.0

Each public contract changes at most once more before 1.0. The run contract
(extractor, state, constructor) breaks in 0.5.0, the data contract (entities,
exporter, logging, dependencies) in 0.6.0, and every later release is
additive. A release is tagged only when sci-etl-cli passes against it and
udg-catalogue completes a run on it. Each breaking change gets a
[MIGRATION.md](MIGRATION.md) entry.

## v0.5.0 — Run contract

Breaking. **Status:** implemented, not yet released. PubMed and
Semantic Scholar keep offset paging and report their caps as truncated:
E-utilities serves at most 9,999 results even through its history server, and
Semantic Scholar's bulk search returns fixed pages of 1,000 papers, which
cannot honor `page_size`. OpenAlex moved to cursor paging. Still open: both
consumers moving to 0.5.0, and a live check of how long OpenAlex cursors stay
valid.

- **Extractor pages and cursors.** Extractors return a parsed `ListingPage`
  from `fetch_page(query, cursor, page_size)`, and the pipeline de-duplicates.
  Saved state holds an opaque cursor instead of an offset. A listing that
  stops at a source's result cap is reported as truncated instead of ending
  silently, and the next run starts from the first page instead of the cap.
- **Failure tracking.** A record that keeps failing, on pages that otherwise
  make progress, is quarantined after `max_attempts` runs instead of holding
  the saved position forever. An outage never quarantines records.
- **Schema versions.** Every SQLite store and the JSON state file record a
  schema version and migrate files written by 0.4.
- **Typed seams.** Keyword-only constructors and dataclasses, and explicit
  signatures on `ETLPipeline` and every `from_config`.
- **Strict config sections.** Unknown keys in bundled sections fail
  validation, with an opt-out on `BaseAppConfig` subclasses.
- **Table sinks.** `SqlTableSink` and `Plotly3DSink` replace the exporters
  that take a `DataFrame`.
- **Removals and deprecations.** What 0.4 deprecated is removed. The blocking
  orchestration contracts and their adapters, `logger=` callables,
  `configure_logging`, `AsyncExporter.export`, and `AsyncCsvUpsertExporter`
  are deprecated. Python 3.10 support ends.

Exit criteria: both consumers run on 0.5.0, a run after a capped run starts
from the first page, and files written by 0.4.0 open in every store.

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
  repeated measurements, and evidence graphs built on the 0.6.0 claims, in a
  separate package that builds on 0.7.0.
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

These appeared on earlier roadmaps and were withdrawn.

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

---

Have a use case the roadmap does not cover? Open a
[feature request](.github/ISSUE_TEMPLATE/feature_request.md).
