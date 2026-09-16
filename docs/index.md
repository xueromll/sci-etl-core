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

Prefer configuration to code? The [`sci-etl` command-line tool](cli/index.md)
runs these pipelines from a single YAML file.

<div class="grid cards" markdown>

- **Get started**

    ---

    Install the extras you need and run your first pipeline over arXiv.

    [Installation](getting-started/installation.md) ·
    [Quick start](getting-started/quick-start.md)

- **Search what you collected**

    ---

    Boolean and hybrid search, metadata facets, and graphs of related papers
    over a local SQLite index.

    [Local search and discovery](guide/search/index.md)

- **Run it from YAML**

    ---

    Initialize, validate, search, and run extraction projects without writing
    wiring code.

    [sci-etl CLI](cli/index.md)

- **Look up an API**

    ---

    Every public class and function, generated from the source.

    [API reference](reference/index.md)

</div>

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

## Getting help

- Questions and bugs go to the
  [issue tracker](https://github.com/xueromll/sci-etl-core/issues).
- Moving an existing pipeline onto the library? Follow the
  [migration guide](project/migration.md).
- Contributions are welcome — see [Contributing](project/contributing.md).
- Please report vulnerabilities privately, as described in
  [Security](project/security.md).
