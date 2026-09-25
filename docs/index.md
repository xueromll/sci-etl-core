# sci-etl-core

`sci-etl-core` is a Python library for turning scientific papers from any field
into structured, searchable data. It fetches papers from arXiv, PubMed,
OpenAlex, and Semantic Scholar, reads their full text, extracts the values you
ask for with an LLM, and keeps the papers searchable on your own machine.

udg-catalogue shows the result. It screens astrophysics papers on arXiv,
extracts measurements of ultra-diffuse galaxies, and publishes a cross-matched
catalog of 1,285 objects, with keyword and semantic search over the papers
behind it. `sci-etl-core` supplies the fetching, parsing, extraction, caching,
resumable state, and search, while udg-catalogue adds the astronomy: prompts,
validation rules, sky-position matching, and the dashboard.

Nothing in the library is tied to astronomy. Field knowledge lives in your
prompts, validators, and normalizers, so the same building blocks work for any
field of science.

<div class="grid cards" markdown>

- **Run it from YAML**

    ---

    Initialize, validate, search, and run extraction projects without writing
    wiring code.

    [sci-etl-cli](cli/index.md)

- **See a complete project**

    ---

    From an arXiv query to a published catalog and a searchable memory of the
    papers behind it.

    [udg-catalogue](https://github.com/xueromll/udg-catalogue)

- **Get started**

    ---

    Install the extras you need and run your first pipeline over arXiv, then
    point it at [PubMed, Semantic Scholar, or OpenAlex](guide/sources.md).

    [Installation](getting-started/installation.md) ·
    [Quick start](getting-started/quick-start.md)

- **Search what you collected**

    ---

    Boolean and hybrid search, metadata facets, and graphs of related papers
    over a local SQLite index.

    [Local search and discovery](guide/search/index.md)

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
  implementations plug in through `Sync*Adapter` wrappers. Run the whole
  pipeline, or use only the parts you need, such as search.
- **Async-first orchestration** — every component is an `async`
  implementation. `AsyncETLPipeline` processes records with bounded
  concurrency, and `ETLPipeline` runs the same pipeline from blocking code.
- **Explicit failure signaling** — a transport fault or malformed listing
  aborts the run with `PipelineAborted` (carrying the partial count) instead of
  looking like the end of the data. A single failing record is logged and left
  for the next run, and records that keep failing while nothing is processed
  stop the run instead of burning through the rest of the listing.
- **Resumable, crash-safe state** — plain-file or SQLite backends record
  processed ids, the listing cursor, and failed attempts, so a record that
  keeps failing is quarantined; CSV and metadata writes use atomic
  renames. Newest-first listings pick up new papers without rescanning.
- **Graceful shutdown** — Ctrl+C or SIGTERM lets in-flight records finish,
  flushes state, and raises `PipelineInterrupted`.
- **Polite retries and rate limits** — every bundled extractor and the
  OpenAI-compatible chat and embedding clients wait as long as a throttled
  response's `Retry-After` header asks, up to a configurable cap, and take
  rate limiters that can be shared and set per host.
- **Progress events, metrics, and token usage** — typed per-record events,
  run metrics with counts, durations, and failures, and the tokens each run
  used.
- **LLM response caching** — an in-memory or SQLite cache answers repeated
  prompts without another API call.
- **Semantic memory (optional)** — chunk and embed full texts into an
  in-memory or SQLite vector store, search for similar articles, or gate
  relevance by embedding similarity instead of an LLM call.
- **Local search and discovery** — Boolean queries over a SQLite FTS5 text
  index that needs only the standard library, hybrid search that fuses BM25
  with embedding similarity, metadata facets, and graphs of related papers.
- **Dependency injection everywhere** — HTTP clients, parsers, models,
  prompts, and destinations are constructor arguments.
- **Concrete implementations included** — arXiv, PubMed, Semantic Scholar,
  and OpenAlex extractors; OpenAI-compatible chat and embedding clients; local
  sentence-transformers embedder; PDF / LaTeX / HTML / DOCX / JATS XML parsers;
  CSV upsert, SQL table, and 3D Plotly exporters; dataframe processors and
  record validators.
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
