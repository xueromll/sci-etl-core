# Changelog

All notable changes to sci-etl-core are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Until 1.0, a minor release may
change behavior; each such change is listed under **Changed**.

## [0.4.0] - Unreleased

### Added

- Discovery graphs in `sci_etl_core.search`. `build_discovery_graph` grows the
  neighborhood of a seed record breadth-first from one or more edge sources,
  keeps only mutual nearest neighbors by default, and groups the records into
  communities by deterministic label propagation. `GraphParams` bounds the
  depth, fanout, minimum edge weight, node count, and label-propagation
  passes, and `DiscoveryGraph.communities_converged` reports whether the pass
  limit cut label propagation short. `filter_graph` narrows a built graph to
  matched records and metadata filters without any I/O. `label_communities`
  and `select_edges` are public as well.
- Edge sources behind a new `AsyncEdgeSource` interface.
  `EmbeddingEdgeSource` relates records by cosine similarity in the vector
  memory, and `MetadataEdgeSource` by the share of tags two records have in
  common, such as arXiv categories and authors.
- `sci_etl_core.discovery`, a read-model for user interfaces: `Facet` and
  `DiscoveryResult`, also exported from `sci_etl_core`. Importing it loads no
  store and no optional dependency.

## [0.3.0] - Unreleased

### Added

- Local Boolean search in `sci_etl_core.search`, which needs only the standard
  library:
  - A query language with terms, `"phrases"`, `prefix*` terms, `title:`,
    `abstract:`, and `body:` scopes, `AND`, `OR`, and `NOT` (also written
    `&&`, `||`, `-`, or, for `AND`, nothing), and parentheses. `parse_query`
    returns a normalized AST, and a malformed query raises
    `SearchQueryError`, whose `position` and `token` locate the fault.
    `describe` turns a query into chips for display.
  - `AsyncSqliteFts5Store`, a durable text index on SQLite FTS5. It ranks by
    BM25 with per-field `BM25Weights`, returns plain-text snippets with
    highlight offsets, filters by metadata (`MetadataFilter`), counts facets
    over its `facet_keys`, and offers `optimize`, `rebuild_index`,
    `rebuild_tags`, and `integrity_check` for maintenance. `fts5_available()`
    reports whether the interpreter's SQLite includes FTS5.
  - `InMemoryTextSearchStore`, which matches the same records as the FTS5
    store.
  - `AsyncSearchIndexer`, the text-index counterpart of `AsyncChunkIngestor`.
  - Rank fusion with `reciprocal_rank_fusion`, the default, or
    `normalized_score_fusion`, configured by `FusionParams`.
  - `AsyncHybridSearcher`, which runs a lexical, semantic, or hybrid search
    and reports in `SearchOutcome.degraded` and `SearchOutcome.skipped` which
    retrieval legs failed or had nothing to run.
- `AsyncCompositeIngestor`, which sends each record to several memory backends
  at once, such as the vector memory and a text index, so that a memory fault
  in one does not stop the others.
- `MemoryIngestor`, the protocol a `memory_ingestor` satisfies, and
  `MEMORY_FAULTS`, the exceptions the pipeline treats as memory faults.
- `SearchError`, with its subclasses `SearchQueryError` and
  `SearchStoreError`.
- A `search` extra. It installs nothing, because search needs only the
  standard library; it lets a requirements file say why the package is there.

### Changed

- `AsyncETLPipeline(memory_ingestor=)` accepts any `MemoryIngestor`. A
  `SearchStoreError` during memory ingest is logged, and the record's entities
  are still exported, as for an embedding fault. A `SearchQueryError` is not a
  memory fault and fails the record.
- `RawRecord.metadata` is no longer empty for arXiv records:
  `AsyncArxivExtractor` fills it with `categories`, `authors`, `published`,
  and `year`. Code that compared `metadata == {}` will notice. The chunk
  metadata `AsyncChunkIngestor` stores is unchanged.
- `AsyncSqliteEmbeddingStore` runs on a shared internal SQLite runner. This is
  behavior-preserving: exception types, messages, transactions, and
  cancellation behavior are unchanged.

### Fixed

- `AsyncSqliteStateManager`: cancelling a task that is awaiting a state
  operation no longer releases the connection while its worker thread is still
  using it. The next operation waits for that thread to finish.

## [0.2.0] - Unreleased

### Security

- `load_config` and `load_config_async` no longer copy pydantic's error text
  into `ConfigurationError`. That text could include the raw settings, and with
  them an API key read from the environment. The message now lists each failing
  key and the reason without its value, and the validation error is no longer
  chained to it.

### Added

- `validate_config(config_cls, raw, source)` validates settings loaded by other
  means with the same secret-safe messages.
- `Retry-After` support. `AsyncArxivExtractor`, `AsyncOpenAICompatibleClient`,
  and `AsyncOpenAIEmbedder` wait as long as a throttled or failing response
  asks, through `Retry-After` or the `retry-after-ms` header OpenAI-compatible
  APIs send, when that is longer than their backoff. The new `max_retry_after`
  argument caps the wait (default 60 seconds).
- The arXiv extractor logs each retry and how long it waits.
- Token usage. `AsyncOpenAICompatibleClient.usage` and
  `AsyncOpenAIEmbedder.usage` return a `TokenUsage` snapshot with `requests`,
  `prompt_tokens`, `completion_tokens`, and `total_tokens`. The `usage` property
  on `AsyncLLMClient` and `AsyncEmbedder` returns `None` unless overridden.
- ruff and mypy run in CI, and a `lint` extra installs them locally.
- This changelog.

### Changed

- The OpenAI SDK's built-in retries are turned off in the chat and embedding
  clients, so `max_retries` is now the total number of attempts. Before, the
  SDK could retry each of those attempts again on its own.
- Invalid-settings messages start with `Invalid configuration in <file>:` and
  put each problem on its own line.
- `AsyncETLPipeline.__aexit__` is annotated to return `None`, so type checkers
  know `async with pipeline` never suppresses an exception.

## [0.1.2] - 2026-09-14

### Fixed

- `max_concurrency` of 0 left every record waiting forever. Values below 1 now
  raise `ValueError`, as do a `page_size` below 1 and a negative `total_limit`.
- A single failed record on a page of otherwise irrelevant records aborted the
  whole run. A run now aborts only when a second page fails with nothing
  processed before any progress, or when the listing ends right after such a
  page.
- The pipeline waited `sleep_between` once more after reaching `total_limit`.
- A `max_retries` below 1 made the arXiv extractor, LLM client, and embedder
  fail without a single attempt. It now raises `ValueError`.
- `configure_logging` failed when the log file's folder was missing, and
  ignored a different file or level on later calls.
- `AsyncFileStateManager` silently stripped whitespace from record ids, so such
  records were processed again on every run. It now rejects them, and the
  pipeline skips blank ids.
- `last_run_at` is recorded in UTC with an offset instead of naive local time.

### Added

- `PipelineConfig.page_size` and `PipelineConfig.search_delay`.
- Range validation for every config section.

### Changed

- The release workflow uploads the built files to a GitHub release that
  already exists instead of failing.

## [0.1.1] - 2026-09-14

### Added

- A tag-triggered release workflow that runs the CI suite, checks the tag
  against the project version, and publishes to PyPI with trusted publishing.
- Package metadata for PyPI: license, keywords, classifiers, and project URLs.

## [0.1.0] - 2026-09-13

First tagged release: the async pipeline and its blocking facade, the arXiv
extractor, OpenAI-compatible chat and embedding clients, PDF, LaTeX, and HTML
parsers, CSV, SQL, and Plotly exporters, dataframe processors and validators,
file and SQLite state, semantic memory, and the udg-catalogue migration guide.

[0.4.0]: https://github.com/xueromll/sci-etl-core/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/xueromll/sci-etl-core/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/xueromll/sci-etl-core/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/xueromll/sci-etl-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/xueromll/sci-etl-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xueromll/sci-etl-core/releases/tag/v0.1.0
