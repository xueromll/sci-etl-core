# Changelog

All notable changes to sci-etl-core are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Until 1.0, a minor release may
change behavior; each such change is listed under **Changed**.


## [Unreleased]

### Added

- `AsyncLLMClient.invalidate(system_prompt, user_content)` reports a rejected
  response, and `AsyncLLMResponseCache.delete(key)` removes one entry; both
  bundled caches implement it.
- `AsyncOpenAICompatibleClient` and `CachingLLMClient` expose `base_url` and
  `temperature`, and every `AsyncLLMClient` exposes `response_format`, which
  defaults to `{"type": "json_object"}`. `response_cache_key` accepts all three
  as keywords.

### Changed

- An empty LLM completion now fails the record instead of settling it.
  `AsyncOpenAICompatibleClient.complete_json` raises `LLMError` where it
  returned `{}`, so the pipeline retries the record on the next run instead of
  marking it processed with nothing exported.
- `AsyncLLMEntityExtractor.extract` raises `LLMError` when the response holds
  no entity list: it is empty, or it has several keys and none is
  `result_key`. It returned `[]`, and the record was marked processed.
- `AsyncLLMRelevanceFilter` and `AsyncEmbeddingRelevanceFilter` with
  `default_on_error=False` fail closed: a failed call or an unclear verdict
  raises, and the record is retried on the next run. It was read as
  irrelevant, and the record was marked processed for good.
- The LLM cache key now includes the endpoint's `base_url`, the temperature,
  and the response format, so an answer cached for one provider, temperature,
  or format is no longer served for another. Responses cached by earlier
  releases are not found, and the first run after upgrading calls the LLM for
  every request.
- A third-party `AsyncLLMResponseCache` without `delete` keeps serving the
  responses the library rejects. Implement `delete`, or accept the replay.
- `AsyncSqliteEmbeddingStore.query` is much faster when called repeatedly. The
  store keeps its vectors in memory and rereads them only after the file
  changes, scores them in one NumPy product, and reads text and metadata for
  the returned chunks only. A discovery graph over a 9,000-chunk memory builds
  about four times faster. The store now holds its vectors in memory between
  queries until it is closed.

### Fixed

- `CachingLLMClient` no longer replays a response the entity extractor or the
  relevance filter rejected. The rejected response was cached, so every retry
  got the same answer until the record was quarantined, without the model
  being asked again.

## [0.5.0] - 2026-09-25

This release changes how extractors page through a listing, what run state is
saved, and how the pipeline is constructed. State saved by 0.4 is upgraded
automatically. See "Upgrading to 0.5" in MIGRATION.md for code changes.

### Added

- **Cursor paging.** Extractors return a `ListingPage` from `fetch_page`, with
  the next page's cursor. Extractors that page by offset also implement
  `OffsetListing`, which `newest_first` runs and `run(start_index=)` require.
- **Quarantine for records that keep failing.** `run(max_attempts=3)` skips a
  record that has failed in 3 runs. `RunMetrics.quarantined` counts skipped
  records. Both bundled state managers store the attempts and last error of
  each record.
- **Result caps are reported.** `RunMetrics.listing_truncated`,
  `PageFetched.truncated`, and `PipelineMetadata.truncated` show when a source
  stopped at its result cap. Progress events also include the page `cursor`.
- **Table sinks.** `SqlTableSink` and `Plotly3DSink` in
  `sci_etl_core.processors.sinks` write a post-processed `DataFrame`.
- **Schema versions.** The SQLite state database, LLM cache, and embedding
  store, and the file state, record a schema version. A file written by a
  newer release is refused, with `StateStoreError` for state files.
- `StaleCursorError`, for a cursor the source no longer accepts.
- `BaseAppConfig.strict_sections`, to opt out of strict config validation.
- `LegacyExtractorAdapter`, which runs an extractor written for 0.4 until it is
  ported. It is already deprecated.

### Changed

- **Breaking:** `AsyncExtractor.fetch_page(query, cursor, page_size)` replaces
  `search` and `parse_listing`. The pipeline now skips processed records
  itself.
- **Breaking:** `PipelineMetadata.cursor` replaces `last_start_index`.
- **Breaking:** pipeline constructors take the five collaborators by position
  or name and all other arguments by keyword. `run()` takes every argument
  after `query` by keyword.
- **Breaking:** `RawRecord`, `PipelineMetadata`, `TokenUsage`, `RunMetrics`,
  and the progress events must be constructed with keyword arguments.
- **Breaking:** unknown keys in the library's config sections, such as
  `search.bm25.titel`, fail validation instead of being ignored.
- **Breaking:** Python 3.11 or newer is required.
- A run that reaches a source's result cap now completes, and the next run
  starts again from the first page instead of stopping at the cap.
- A cursor the source rejects restarts the listing from the first page once.
- `AsyncOpenAlexExtractor` pages with OpenAlex cursors and is no longer limited
  to the first 10,000 results. It no longer supports `newest_first`.
- `AsyncPubMedExtractor` and `AsyncSemanticScholarExtractor` stop at the last
  page of results without an extra empty request.

### Deprecated

These keep working in 0.5 and are removed in 0.6.0.

With a replacement available now (`DeprecationWarning`):

- the blocking `Extractor`, `StateManager`, `Exporter`, `LLMClient`,
  `RelevanceFilter`, and `EntityExtractor` interfaces and the `Sync*Adapter`
  classes;
- `LegacyExtractorAdapter`;
- `AsyncSqlTableExporter` and `AsyncPlotly3DExporter`, replaced by
  `SqlTableSink` and `Plotly3DSink`.

With a replacement arriving in 0.6.0 (`PendingDeprecationWarning`, so nothing
needs to change yet):

- `logger=` arguments and `configure_logging`;
- `AsyncETLPipeline(destination=)`;
- `AsyncExporter.export` and `AsyncCsvUpsertExporter`.

### Removed

- The config keys `pipeline.max_records` and `pipeline.max_workers`, the
  matching `PipelineConfig` properties, and `run(max_records=)`. Use
  `total_limit` and `max_concurrency`.
- `build_retrying_session`, and `requests` from the `full` extra.

### Fixed

- `AsyncPubMedExtractor` no longer requests results past the 9,999th, which
  PubMed rejects.

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

[Unreleased]: https://github.com/xueromll/sci-etl-core/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/xueromll/sci-etl-core/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/xueromll/sci-etl-core/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xueromll/sci-etl-core/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xueromll/sci-etl-core/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xueromll/sci-etl-core/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/xueromll/sci-etl-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/xueromll/sci-etl-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xueromll/sci-etl-core/releases/tag/v0.1.0
