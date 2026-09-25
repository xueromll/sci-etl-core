# Changelog

All notable changes to sci-etl-core are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Until 1.0, a minor release may
change behavior; each such change is listed under **Changed**.

## [Unreleased]

The 0.5.0 run contract. MIGRATION.md, "Upgrading to 0.5", covers every item
below that needs a change in calling code.

### Added

- `ListingPage`, the parsed page `AsyncExtractor.fetch_page` returns, with an
  opaque `next_cursor` and a `truncated` flag for a source that stopped at its
  own result cap.
- `OffsetListing`, the protocol of an extractor whose cursors are decimal
  offsets. `newest_first` runs and `run(start_index=)` above 0 need it.
- `StaleCursorError`, raised by an extractor that no longer accepts a cursor,
  and `StateStoreError`, raised by a state manager for a file written by a newer
  sci-etl-core.
- `LegacyExtractorAdapter`, which runs an extractor written against the 0.4
  `search` and `parse_listing` contract. It is deprecated on arrival.
- Failure tracking: `AsyncStateManager.record_failure` and `failure_counts`,
  with defaults that track nothing; `run(max_attempts=3)`; and
  `RunMetrics.quarantined`. Both bundled state managers store the attempts and
  the last error per record, truncated to 4,096 characters.
- `RunMetrics.listing_truncated`, `PageFetched.truncated`, and
  `PipelineMetadata.truncated` report a listing that stopped at a result cap.
  `RunStarted`, `PageFetched`, and `PageFinished` gain `cursor`.
- `BaseAppConfig.strict_sections`, the opt-out from strict config sections.
- `SqlTableSink` and `Plotly3DSink` in `sci_etl_core.processors.sinks`, blocking
  `TableSink`s that take a post-processed `DataFrame`.
- Schema versions in `PRAGMA user_version` for the SQLite state database, the
  SQLite LLM cache, and the SQLite embedding store, and a `schema_version` key
  in the file state's metadata. Each store refuses a file written by a newer
  release.

### Changed

- `AsyncExtractor` has `fetch_page(query, cursor, page_size)` in place of
  `search` and `parse_listing`, and no longer receives the processed ids: the
  pipeline skips processed records itself and parses each listing page once.
- `PipelineMetadata.cursor` replaces `last_start_index`. Both bundled state
  managers read a file written by 0.4 and turn its saved offset into the cursor.
- `AsyncOpenAlexExtractor` pages with OpenAlex cursors, so a listing is no
  longer limited to its first 10,000 works. It is not an `OffsetListing`, so it
  no longer supports `newest_first` runs, and an offset saved by 0.4 restarts
  its listing from the first page once.
- `AsyncPubMedExtractor` and `AsyncSemanticScholarExtractor` mark the page that
  reaches their result cap, 9,999 and 1,000 results, as `truncated`, and end
  the listing on the page that reaches the search's result count.
  `AsyncPubMedExtractor` no longer requests the offset 9,999, which E-utilities
  rejects.
- A listing that stops at a result cap completes the run and resets the saved
  cursor, so the next run pages the reachable results again instead of ending
  at the cap. A stale cursor restarts the listing from its first page once per
  run.
- A record that fails in `max_attempts` runs, on pages that processed another
  record, is skipped as quarantined in later runs. Pass `max_attempts=None` for
  the 0.4 behavior.
- `AsyncETLPipeline` and `ETLPipeline` take the five collaborators positionally
  and every other argument by keyword, with typed `sleep`, `closeables`, and
  `usage_sources`. Every argument of `run` after `query` is keyword-only, and
  `page_size` defaults to 100. Both `from_config` methods list their arguments
  instead of taking `**arguments`.
- `RawRecord`, `PipelineMetadata`, `TokenUsage`, `RunMetrics`, and every event
  dataclass are keyword-only.
- A key a bundled config section does not declare, such as
  `search.bm25.titel`, fails validation.
- sci-etl-core requires Python 3.11 or newer.

### Deprecated

These still work in 0.5.x, emit a `DeprecationWarning`, and are removed in
0.6.0:

- every `logger=` argument, and `configure_logging`;
- the blocking `Extractor`, `StateManager`, `Exporter`, `LLMClient`,
  `RelevanceFilter`, and `EntityExtractor` contracts, when subclassed outside
  the library, and the `Sync*Adapter`s;
- `LegacyExtractorAdapter`;
- `AsyncETLPipeline(destination=)`;
- `AsyncExporter.export` and `AsyncCsvUpsertExporter`, whose replacements
  arrive in 0.6.0;
- `AsyncSqlTableExporter` and `AsyncPlotly3DExporter`, replaced by
  `SqlTableSink` and `Plotly3DSink`.

### Removed

- The config keys `pipeline.max_records` and `pipeline.max_workers`, the
  `PipelineConfig.max_records` and `max_workers` properties, and
  `run(max_records=)`.
- `sci_etl_core.http.build_retrying_session`, `requests` from the `full` extra,
  and `types-requests` from the `lint` extra.

## [0.4.1] - 2026-09-25

### Changed

- `HttpConfig.user_agent` and `build_async_client` default to
  `sci-etl-core/<installed version>` instead of `sci-etl-core/0.1`.

### Fixed

- `load_config_async` and `AsyncCsvUpsertExporter` check whether a file exists
  in a worker thread instead of blocking the event loop.
- The `sql` and `full` extras require `sqlalchemy[asyncio]`, so they install
  `greenlet`. SQLAlchemy 2.1 no longer installs it by default, and without it
  `AsyncSqlTableExporter` could not be imported.

## [0.4.0] - 2026-09-16

### Added

- `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, and
  `AsyncOpenAlexExtractor`. Each fills `RawRecord.metadata` with `authors` and
  `categories`, and `published` and `year` when the source has a date, and
  retries transport faults, `408`, `429`, and server errors, honoring
  `Retry-After`. `AsyncOpenAlexExtractor` also stores the works a paper cites
  under `references`.
- `DocxParser` for Word `.docx` files, and `JatsXmlParser` for JATS XML, whose
  `parse_article` returns a `JatsArticle` with sections, authors, keywords,
  identifiers, and references.
- LLM response caching: `CachingLLMClient` wraps any `AsyncLLMClient` and
  answers repeated requests from an `AsyncLLMResponseCache`, either
  `InMemoryLLMResponseCache` or `AsyncSqliteLLMResponseCache`. A cache fault is
  logged and counted in `CacheStats`, raised as `LLMCacheError` by the stores,
  and never fails a completion.
- Graceful shutdown: `AsyncETLPipeline(shutdown=)` and
  `ETLPipeline(shutdown=)` take a `ShutdownSignal`, so SIGINT, SIGTERM, or
  `request()` lets in-flight records finish and raises `PipelineInterrupted`,
  a subclass of `PipelineAborted`. Every run now ends with the state manager's
  `flush()`, however it ends.
- Progress events and run metrics: `on_event` receives `RunStarted`,
  `PageFetched`, `RecordFinished`, `PageFinished`, and `RunFinished` from
  `sci_etl_core.observability`, and `last_run_metrics` returns `RunMetrics`
  with counts, durations, the run's outcome, and the tokens the
  `usage_sources` used. `TokenUsage` supports `+` and `-`.
- `run(newest_first=True)` picks up new submissions in a newest-first listing
  without rescanning from offset 0. `PipelineMetadata` gains `head_ids`,
  `head_offset`, and `tail_ids`, which both state backends save.
- `rate_limiter` on every bundled extractor, `AsyncOpenAICompatibleClient`,
  and `AsyncOpenAIEmbedder`, and `HostRateLimiter` for limits per host.
- Components built from the config: `AsyncArxivExtractor.from_config`,
  `AsyncOpenAICompatibleClient.from_config`, `AsyncETLPipeline.from_config`,
  and `ETLPipeline.from_config`, plus `HttpConfig.build_client()`,
  `RateLimitConfig.build_limiter()`, and `PipelineConfig.run_arguments()`. A
  `search` config section builds `BM25Weights`, `FusionParams`,
  `HybridParams`, and `GraphParams`. `PipelineConfig` gains `newest_first`, and
  `AsyncOpenAICompatibleClient` a `model` property.
- `AsyncLLMEntityExtractor(validator=, logger=, label_field=)` drops and logs
  the entities a `RecordValidator` rejects.
- `ScatterPlotConfig` takes `hover_data_columns`, `hover_template`,
  `color_continuous_scale`, `color_range`, `color_label`, `marker`, and
  `layout`.
- `ValueClipStep` clamps numeric columns during post-processing, and
  `TableLayoutStep` sorts rows and orders columns.
- `NEAR(...)` proximity queries in the query language, as the `Near` node with
  `NEAR_DISTANCE`, supported by both text stores, and `QueryChip.near`.
- Range filters: `RangeFilter` keeps records whose tags lie between integer or
  text bounds, such as years or ISO 8601 dates, in both text stores, hybrid
  search, and `filter_graph`. `AsyncTextSearchStore.range_counts` counts the
  matches in each of several ranges. `SearchFilter` names either filter type.
- Richer snippets: `TextHit.snippets` and `FusedHit.snippets` hold a `Snippet`
  for every field with a highlighted match. `passage_snippet` and
  `snippet_window` build snippets of other text.
- `backfill_text_index` builds a text index from the chunks in the vector
  memory, removing the words overlapping chunks share (`merge_passages`), and
  reports what it did in a `BackfillReport`. `AsyncEmbeddingStore.iter_records`
  yields each record's passages as a `StoredRecord` without loading vectors,
  implemented by both bundled stores.
- `AsyncSimilarArticleFinder.find_best_chunks` returns each article's best
  chunk, text included. `SlidingWindowChunker` exposes `chunk_words` and
  `overlap_words`.

### Changed

- `PipelineConfig.max_records` is now `total_limit`, and `max_workers` is
  `max_concurrency`. The old YAML keys and attributes still work with a
  `DeprecationWarning` until 0.5.0, and loading a config that sets an old and
  a new key to different values raises `ConfigurationError`. `run(max_records=)` is
  deprecated the same way.
- `build_retrying_session` is deprecated and will be removed in 0.5.0, along
  with `requests` in the `full` extra.
- A hybrid search hit found only by the semantic leg now carries a snippet of
  its best chunk in `snippet`, `highlights`, and `snippets`, where these used to
  be empty. Code that showed the abstract whenever `snippet` was empty should
  check `lexical_rank is None` instead.
- `ETLPipeline.run` waits for the background loop in short slices, so a
  signal handler on the calling thread runs promptly, and a
  `KeyboardInterrupt` cancels the run on the background loop.

## [0.3.0] - 2026-09-15

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

## [0.2.0] - 2026-09-14

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

[Unreleased]: https://github.com/xueromll/sci-etl-core/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/xueromll/sci-etl-core/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xueromll/sci-etl-core/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xueromll/sci-etl-core/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xueromll/sci-etl-core/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/xueromll/sci-etl-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/xueromll/sci-etl-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xueromll/sci-etl-core/releases/tag/v0.1.0
