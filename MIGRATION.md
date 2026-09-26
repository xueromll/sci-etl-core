# Migration Guide

This guide lists what changes for existing code when you move to a new
release of `sci-etl-core`, newest release first. [CHANGELOG.md](CHANGELOG.md)
lists every change, including the additions that need no action.

Pin a minor release range, such as `sci-etl-core>=0.6.0,<0.7`, and raise the
upper bound after your tests pass on the next minor release. Moving from one
minor release to a later one, apply each section in between, oldest first.

To move an existing research pipeline onto the library for the first time,
follow the worked example in
[Migrating a pipeline](https://xueromll.github.io/sci-etl-core/latest/guide/migrating-a-pipeline/).

- [Upgrading to 0.6](#upgrading-to-06)
- [Upgrading to 0.5.1](#upgrading-to-051)
- [Upgrading to 0.5](#upgrading-to-05)
- [Upgrading to 0.4](#upgrading-to-04)
- [Upgrading to 0.3](#upgrading-to-03)

---

## Upgrading to 0.6

0.6 changes the data contract: what an entity extractor returns, how an
exporter receives entities, how the library logs, and what a base install
contains. It is the last release before 1.0 that breaks an existing contract.
Require the new minor with the extras you use:

```text
sci-etl-core[config,async,arxiv,llm,pdf,processors]>=0.6.0,<0.7
```

State files and databases, LLM caches, embedding stores, and text indexes
written by 0.5 open unchanged. Cached LLM answers stay valid: a request
without a schema has the same cache key it had in 0.5.1.

### Install the extras you import

The base install now requires only Pydantic. PyYAML and python-dotenv moved
to the `config` extra, Beautiful Soup and lxml to `arxiv`, `html`, and `xml`,
and pandas to `processors`. `aiofiles` and `aiosqlite` are no longer installed
by any extra. Importing a component whose extra is missing raises
`ModuleNotFoundError` naming the package:

| You use | Add the extra |
|---------|---------------|
| `load_config`, `load_config_async`, `load_yaml` | `config` |
| `AsyncArxivExtractor` | `async`, `arxiv` |
| `AsyncPubMedExtractor` | `async`, `xml` |
| `JatsXmlParser`, `DocxParser` | `xml` |
| `HtmlTextParser`, or `AsyncLLMEntityExtractor` on full text that starts with markup | `html` |
| anything in `sci_etl_core.processors` except the validators | `processors` |

`full` still installs every bundled component except local embeddings.

### `.env` files are read only when asked

`load_config` and `load_config_async` no longer look for a `.env` file
implicitly. Pass the file, or ask for the lookup:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), load_env=True)
config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
```

Without either, the API key must already be in the environment.

### Exporters take the record and their destination

`AsyncExporter.export(data, destination)` is replaced by a lifecycle. The
pipeline calls `open()` before the first listing request, `write(record,
entities)` for every processed record, including one with no entities,
`flush()` after each page, and `aclose()` when the run ends, however it ends.
An exporter takes its destination when it is constructed, so the pipeline's
`destination=` argument is gone:

```python
from sci_etl_core import AsyncCsvExporter, AsyncETLPipeline

pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager,
)
```

`AsyncCsvUpsertExporter` is removed. Its replacement, `AsyncCsvExporter`, does
not merge rows: it writes one row per entity with the `record_id` of the
paper it came from, keeps other keys in an `extra` column, and writes values
unchanged, so a value is never clipped, coerced, or dropped, and two papers
that report one object give two rows. Merge in post-processing, where the
choice is explicit:

```python
import pandas as pd

from sci_etl_core.processors import DeduplicationStep, DefaultKeyNormalizer, NormalizationStep, ProcessorChain

raw = pd.read_csv("results.csv", dtype={"record_id": str, "name": str})
one_row_per_name = ProcessorChain(
    [NormalizationStep("name", DefaultKeyNormalizer()), DeduplicationStep("_norm_key")]
).process(raw)
```

The CSV file is written when the run ends; during a run, pages go to
`results.csv.journal`, which the next run replays if a run crashed. Add
`*.journal` to `.gitignore` next to your output. The new file's header is
`record_id`, your columns, and `extra`, so start a new file rather than
pointing the exporter at one `AsyncCsvUpsertExporter` wrote; the exporter
refuses a file with another header. `AsyncJsonlExporter` writes one JSON line
per record instead.

A custom exporter implements `write` and, if it buffers, sets
`durable_writes = False` and implements `flush`:

```python
from sci_etl_core import AsyncExporter


class DatabaseExporter(AsyncExporter):
    def __init__(self, database):
        self.database = database

    async def write(self, record, entities):
        await self.database.replace_rows(record.record_id, list(entities))
```

`write` must be idempotent, since a crash can repeat a record, and a record
with no entities should clear what an earlier write stored. A record is
marked processed only once its entities are durable: right after `write`, or
after the page's `flush` when `durable_writes` is `False`. A `write` fault
fails the record and counts one attempt, a `flush` fault leaves the page's
written records unsettled without counting an attempt, and an `open` fault
aborts the run before any request. [Run semantics](https://xueromll.github.io/sci-etl-core/latest/guide/run-semantics/)
numbers these as R20 to R23.

`AsyncSqlTableExporter` and `AsyncPlotly3DExporter` are removed; use
`SqlTableSink` and `Plotly3DSink` from `sci_etl_core.processors.sinks`, as
[Table sinks](#table-sinks) shows. `ScatterPlotConfig` is imported from
`sci_etl_core.processors`.

### Entity extractors are typed and record-aware

`AsyncEntityExtractor` is generic in its entity type, and the pipeline calls
`extract_record(record, text)`, whose default calls `extract(text)`. An
extractor that overrides only `extract` needs no change. A wrapper around
another extractor should delegate `extract_record` too, so it keeps working
around an extractor that needs the record, such as `AsyncLLMClaimExtractor`:

```python
from sci_etl_core import AsyncEntityExtractor


class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(self, inner, validator):
        self.inner = inner
        self.validator = validator
        self.requires_record = inner.requires_record

    async def extract(self, text):
        return [entity for entity in await self.inner.extract(text) if self.validator.is_valid(entity)]

    async def extract_record(self, record, text):
        entities = await self.inner.extract_record(record, text)
        return [entity for entity in entities if self.validator.is_valid(entity)]
```

Such a wrapper is usually no longer needed: `AsyncLLMEntityExtractor` takes a
`validator`, logs every rejection with its reasons, and can keep rejected
entities in a rejection store. Every argument after `system_prompt` is now
keyword-only.

To validate entities against a Pydantic model and receive model instances,
pass `schema=`; see
[Typed entities and validation](https://xueromll.github.io/sci-etl-core/latest/guide/typed-entities/).
A custom `AsyncLLMClient` that wraps another should forward
`complete_structured` and accept `schema=` in `invalidate`.

### Validators say why

`RecordValidator.validate(entity)` returns a `ValidationResult` of
`Violation`s. A validator that implements only `is_valid` keeps working. One
that already computes a reason, such as a `rejection_reason` method, can
override `validate` instead, and the reason reaches the log and the rejection
store:

```python
from sci_etl_core.processors import RecordValidator, ValidationResult, Violation


class RangeValidator(RecordValidator):
    def is_valid(self, record):
        return self.validate(record).ok

    def validate(self, record):
        radius = record.get("radius_kpc")
        if radius is not None and not 0.1 <= float(radius) <= 20.0:
            violation = Violation(code="out-of-range", field="radius_kpc", severity="error", message=f"radius {radius} kpc")
            return ValidationResult(violations=(violation,))
        return ValidationResult()
```

### Logging goes through the `logging` module

Every `logger=` argument is removed: from `AsyncETLPipeline`, `ETLPipeline`,
the four extractors, `AsyncLLMEntityExtractor`, `CachingLLMClient`,
`AsyncCompositeIngestor`, `AsyncHybridSearcher`, and `ShutdownSignal`.
`configure_logging` and `sci_etl_core.log_utils` are removed, and so is
`AsyncETLPipeline.log`. Each module logs under its own name below the
`sci_etl_core` logger, so configure logging in the application:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler("output/pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
```

Messages keep their wording. `CachingLLMClient` took `logger` as its fourth
positional argument; a call that passed it positionally now fails with a
`TypeError`.

### Removed names

The 0.5 deprecations are removed: the blocking contracts `Extractor`,
`StateManager`, `Exporter`, `LLMClient`, `RelevanceFilter`, and
`EntityExtractor`; their adapters `SyncExtractorAdapter`,
`SyncRelevanceFilterAdapter`, `SyncEntityExtractorAdapter`,
`SyncExporterAdapter`, `SyncStateManagerAdapter`, and `SyncLLMClientAdapter`;
`LegacyExtractorAdapter`; `AsyncExporter.export` and the `destination`
argument; `AsyncCsvUpsertExporter`, `AsyncSqlTableExporter`, and
`AsyncPlotly3DExporter`; and `configure_logging`. Implement the async
contracts, running blocking work inside them with `asyncio.to_thread`.
`ETLPipeline` stays, and runs the async pipeline from blocking code as before.

From 0.6 on, a deprecated name keeps working for at least two minor releases
before it is removed.

## Upgrading to 0.5.1

0.5.1 breaks no existing call, but three LLM outcomes that used to settle a
record now fail it. The record stays unmarked, its attempt counts toward
`max_attempts`, and the next run retries it:

- **An empty completion.** `AsyncOpenAICompatibleClient.complete_json` raises
  `LLMError` instead of returning `{}`.
- **A response without an entity list.** `AsyncLLMEntityExtractor.extract`
  raises `LLMError` when the response is empty, or has several keys and none
  is `result_key`, instead of returning `[]`.
- **A relevance fault with `default_on_error=False`.**
  `AsyncLLMRelevanceFilter` and `AsyncEmbeddingRelevanceFilter` raise instead
  of reading the fault as "irrelevant", which marked the record processed for
  good.

If your model sometimes answers with an empty object, or with the entity list
under another key, those records now fail and are quarantined after
`max_attempts` runs. Name `result_key` in the prompt. A custom
`AsyncLLMClient` should raise `LLMError` for a response it cannot read rather
than return `{}`.

Records that earlier releases marked processed this way stay marked; only a
run on a fresh state revisits them.

The LLM cache changes too:

- **Every cached response misses once.** The cache key now includes the
  endpoint's `base_url`, the temperature, and the response format, so the
  first run after upgrading calls the LLM for every request. Entries written
  by earlier releases are never read again; delete the cache file, or call `clear()`, to reclaim the
  space. A model name that encodes the temperature, such as
  `"gpt-4o-mini@t0.2"`, is no longer needed.
- **Rejected responses are removed.** `AsyncLLMEntityExtractor` and
  `AsyncLLMRelevanceFilter` call `invalidate` on their client when they reject
  a response, and `CachingLLMClient` deletes it, so the retry reaches the
  model. A custom `AsyncLLMResponseCache` should implement `delete`. A custom
  client that wraps another should forward `invalidate` to it.

## Upgrading to 0.5

0.5 changes how extractors page, what the state saves, and how the pipeline
is constructed. Entities and exporters change in 0.6. Require the new minor
and Python 3.11:

```text
sci-etl-core[async,llm,pdf]>=0.5.0,<0.6
```

State written by 0.4 needs no conversion. `AsyncSqliteStateManager` upgrades
its database in place, and `AsyncFileStateManager` reads the old metadata file
and rewrites it in the new format on the next save. Either way the saved offset
becomes the cursor, so the next run resumes where the last one stopped.

### Extractors return parsed pages

`search` and `parse_listing` are replaced by one `fetch_page`, which returns a
`ListingPage`. The pipeline now skips processed records itself, so an
extractor returns every entry it can read. A source that pages by offset
implements `cursor_for_offset` too, which makes it an `OffsetListing`.

Before:

```python
class MyExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return await self._client.get_page(query, start_index, max_results)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        entries = parse(raw_listing)
        return [entry for entry in entries if entry.record_id not in seen_ids], len(entries)
```

After:

```python
class MyExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = int(cursor or 0)
        entries = parse(await self._client.get_page(query, offset, page_size))
        return ListingPage(
            records=tuple(entries),
            entries=len(entries),
            next_cursor=str(offset + len(entries)) if entries else None,
        )
```

A source with opaque continuation tokens returns the token as `next_cursor`
and leaves out `cursor_for_offset`. A source that stops at its own result cap
returns `truncated=True` and `next_cursor=None` on the page that reaches it.
Until an extractor is ported, `LegacyExtractorAdapter(MyOldExtractor())` runs
it unchanged in 0.5.x, with a `DeprecationWarning`; 0.6 removes the adapter.

A wrapper that forwards to another extractor, such as a progress logger,
forwards `fetch_page`, and `cursor_for_offset` too when it wraps an
`OffsetListing`:

```python
class LoggingExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return self._inner.cursor_for_offset(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self._log(f"Fetching listing page at cursor {cursor or 'start'}")
        return await self._inner.fetch_page(query, cursor, page_size)
```

`newest_first=True` and `start_index` above 0 need an `OffsetListing` and raise
`ValueError` before any request otherwise. `AsyncArxivExtractor`,
`AsyncPubMedExtractor`, and `AsyncSemanticScholarExtractor` are
`OffsetListing`s. `AsyncOpenAlexExtractor` now pages with OpenAlex cursors, so
it reaches past the first 10,000 works but no longer supports `newest_first`;
its first 0.5 run restarts the listing once from the first page, because the
offset 0.4 saved is not an OpenAlex cursor.

### What the state saves

`PipelineMetadata.cursor` replaces `last_start_index`. Code that reads the
saved position reads the cursor, which is a decimal offset for an
`OffsetListing`:

```python
metadata = await state.load_metadata()
saved_offset = int(metadata.cursor or 0)
```

The progress events gain `cursor`. `RunStarted.start_index`,
`PageFetched.offset`, and `PageFinished.offset` still hold the listing offset
for an `OffsetListing` and are `None` for any other extractor.

### Capped listings start over

PubMed stops at 9,999 results, Semantic Scholar at 1,000. In 0.4 a run that
reached the cap saved the cap as its offset, and every later run ended there at
once. In 0.5 the page that reaches the cap ends the run `"completed"`,
`RunMetrics.listing_truncated` reports it, and the saved cursor is reset, so
the next run pages the reachable results again: processed records are skipped
by id, so the rescan costs listing requests, not LLM calls. Narrow the query,
for example by date, to avoid the rescan.

### Records that keep failing are quarantined

A record that fails in 3 runs, each on a page that processed another record, is
skipped as quarantined from the next run on and counted in
`RunMetrics.quarantined`. Failures on a page where nothing was processed, as
during an outage or with a rejected API key, are never counted. To keep the
0.4 behavior, retrying every failed record forever:

```python
await pipeline.run(query, page_size=100, total_limit=500, max_attempts=None)
```

A third-party state manager keeps working unchanged: the new
`record_failure` and `failure_counts` have defaults that track nothing, so it
never quarantines.

### Keyword arguments

`AsyncETLPipeline` and `ETLPipeline` take the five collaborators positionally,
or by name, and everything else by keyword. `run` takes `query` and then
keywords only, and `max_records=` is gone:

```python
pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    exporter,
    state_manager,
    destination="results.csv",
    max_concurrency=4,
)
await pipeline.run("all:galaxy", page_size=50, total_limit=200)
```

`RawRecord`, `PipelineMetadata`, `TokenUsage`, `RunMetrics`, and the events
are keyword-only, so `RawRecord("id", "title", "abstract")` becomes
`RawRecord(record_id="id", title="title", abstract="abstract")`.

### Strict config sections

A key that a bundled section does not declare now fails validation and is
named in the `ConfigurationError`, so a typo such as `search.bm25.titel` or the
earlier key `pipeline.max_records` no longer passes silently. Rename
`pipeline.max_records` to `total_limit` and `pipeline.max_workers` to
`max_concurrency`. An application that must accept unknown keys for now opts
out on its config class, and each dropped key is reported with a `UserWarning`:

```python
class AppConfig(BaseAppConfig):
    strict_sections = False
```

Top-level sections the application defines are kept as before.

### Table sinks

`AsyncSqlTableExporter` and `AsyncPlotly3DExporter` took a `DataFrame` and
could not run in the pipeline. Their replacements are blocking sinks for
post-processing output:

```python
from sci_etl_core.processors.sinks import Plotly3DSink, ScatterPlotConfig, SqlTableSink

catalogue = chain.process(raw_table)
SqlTableSink("sqlite:///catalogue.db", "galaxies", if_exists="replace").write(catalogue)
Plotly3DSink(ScatterPlotConfig("x", "y", "z", color_column="size"), "catalogue.html").write(catalogue)
```

### Deprecations with no replacement before 0.6

These keep working in 0.5.x and emit a `PendingDeprecationWarning`, not a
`DeprecationWarning`, because their replacements ship in 0.6 and there is
nothing to change yet: the `destination` argument, `AsyncExporter.export` and
`AsyncCsvUpsertExporter` (replaced by the exporter lifecycle and
`AsyncCsvExporter`), and every `logger=` argument and `configure_logging`
(replaced by the standard `logging` module). A test suite run with
`-W error::DeprecationWarning` therefore keeps passing while it uses them.

The blocking contracts and their `Sync*Adapter`s, `LegacyExtractorAdapter`,
and the two table exporters emit a `DeprecationWarning`, because their
replacements exist in 0.5; move to the async contracts, which every component
already implements, `fetch_page`, and the table sinks.

`build_retrying_session` is removed, and the `full` extra no longer installs
`requests`.

## Upgrading to 0.4

```text
sci-etl-core[async]>=0.4.0,<0.5
```

0.4 adds new sources, parsers, LLM response caching, graceful shutdown,
progress events, rate limiters, and search features. These changes affect
existing code:

- **Renamed pipeline settings.** `pipeline.max_records` is now `total_limit`
  and `pipeline.max_workers` is `max_concurrency`. The old YAML keys and the
  `PipelineConfig.max_records` and `max_workers` properties still work until
  0.5, with a `DeprecationWarning`, and `run(max_records=)` is deprecated the
  same way. Rename both keys in your config file.
- **More pipeline settings.** `PipelineConfig` now has `page_size`,
  `search_delay`, and `newest_first`. A subclass that only added these fields
  can be deleted.
- **Validation without a wrapper.** `AsyncLLMEntityExtractor` takes
  `validator=`, `logger=`, and `label_field=`, and logs each entity it drops
  as `Entity rejected by validation: <label>`. An extractor that wrapped it
  only to apply a `RecordValidator` can be deleted.
- **Components from the config.** `AsyncArxivExtractor.from_config`,
  `AsyncOpenAICompatibleClient.from_config`, and `AsyncETLPipeline.from_config`
  read the `http`, `llm`, and `pipeline` sections, `config.http.build_client()`
  replaces `build_async_client`, and `config.pipeline.run_arguments()` returns
  the arguments for `run()`, so the settings no longer need copying into
  constructors by hand.
- **Newest-first resume.** `run(newest_first=True)` picks up new arXiv
  submissions without the full rescan that `start_index=0` costs, and saves
  the head of the listing in the metadata file next to `last_start_index`.
  `start_index` can't be combined with it.
- **Plots.** `ScatterPlotConfig` takes `hover_data_columns`,
  `hover_template`, `color_continuous_scale`, and `color_range`, which cover
  the custom hover text and fixed color ranges that used to need a figure
  built by hand.
- **Clamping and table layout.** `ValueClipStep` clamps columns during
  post-processing, and `TableLayoutStep` sorts rows and orders columns, in
  place of project-specific processors that did either.
- **Search from the memory you already have.** A project that stored chunks
  in an `AsyncSqliteEmbeddingStore` can build a text index from them with
  `backfill_text_index` instead of fetching every paper again.
- **Snippets for semantic hits.** A `FusedHit` found only by the semantic leg
  now carries a snippet of its best chunk, where it used to have an empty
  `snippet`. A UI that showed the abstract whenever `snippet` was empty should
  check `lexical_rank is None` instead.
- **Deprecated `requests` helper.** `build_retrying_session` warns and will be
  removed in 0.5, along with `requests` in the `full` extra.

## Upgrading to 0.3

```text
sci-etl-core[async]>=0.3.0,<0.4
```

0.3 adds local search and discovery graphs. These changes affect existing
code:

- **arXiv records carry metadata.** `RawRecord.metadata` now holds
  `categories`, `authors`, `published`, and `year` instead of staying empty.
  Code of your own that reads records, including tests that compare
  `metadata == {}`, sees the new keys. The metadata stored with embedding
  chunks is unchanged.
- **`memory_ingestor` accepts any `MemoryIngestor`.** An `AsyncChunkIngestor`
  works exactly as before. A type hint in your code that names
  `AsyncChunkIngestor` for this argument can widen to `MemoryIngestor`.
- **Search is opt-in.** Nothing changes in a pipeline that passes no text
  index. To add one, pass an `AsyncSearchIndexer`, or an
  `AsyncCompositeIngestor` with a chunk ingestor first, as
  [Local search and discovery](https://xueromll.github.io/sci-etl-core/latest/guide/search/)
  shows. Its `AsyncSqliteFts5Store` goes in `closeables` like any other SQLite
  store.
- **SQLite state is safer under cancellation.** `AsyncSqliteStateManager` no
  longer lets a cancelled operation's worker thread overlap the next
  operation. `AsyncFileStateManager` is unchanged.

Questions or a rough edge in your upgrade? Open an
[issue](.github/ISSUE_TEMPLATE/bug_report.md) — we're happy to help.
