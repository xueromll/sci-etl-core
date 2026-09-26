# State, resuming, and errors

## State backends

Two state backends ship with the library:

- **`AsyncFileStateManager(processed_ids_file, metadata_file)`** stores one
  processed id per line plus a JSON metadata file. It holds OS-level file locks
  and writes metadata atomically.
- **`AsyncSqliteStateManager(database_path)`** uses a WAL-mode SQLite
  database. Add it to `closeables` so its connection is closed. Its `flush()`
  checkpoints the WAL.

Both record a schema version: the SQLite database in `PRAGMA user_version`,
the metadata file in a `schema_version` key. Each reads files written by
sci-etl-core 0.4, whose saved offset becomes the cursor, and raises
`StateStoreError` for a file written by a newer release instead of reading or
overwriting it. A custom `AsyncStateManager` implements the four abstract
methods; `record_failure`, `failure_counts`, and `flush` have defaults.

## Resuming

Each run starts at the saved `cursor` and skips ids that were already
processed. The cursor is saved after every page, but it only moves past a page
once every record on it is settled, meaning processed, marked irrelevant, or
skipped as quarantined. When a record fails, or is left over because
`total_limit` was reached, the cursor stays at the start of that page for the
rest of the run, so the next run revisits it while skipping everything already
processed. When a run reaches the end of the listing, an extractor that pages
by offset saves the offset past the last entry, and any other extractor saves
no cursor, so the next run starts from the first page.
[Run semantics](run-semantics.md) lists every rule a run follows, each with
the test that checks it.

Records are exported before they are marked processed, so a crash between the
two re-exports that record on the next run. `AsyncCsvUpsertExporter` absorbs
this; an appending exporter of your own should tolerate duplicates.

`AsyncFileStateManager` raises `OSError` when a state file exists but can't be
read, rather than treating it as empty. It rejects record ids that contain a
line boundary or have leading or trailing whitespace, since neither would read
back unchanged. Metadata content that isn't valid falls back to the first page,
which only costs a rescan. Both backends record `last_run_at` as an ISO 8601
timestamp in UTC.

## Records that keep failing

A record that fails in every run, such as a paper whose PDF crashes the
parser, would otherwise be retried forever and hold the saved cursor at its
page. `run(max_attempts=3)`, the default, counts each failed attempt through
the state manager and, from the next run on, skips a record whose attempts
reached `max_attempts` as quarantined. A quarantined record is not processed
or retried, counts as settled for the saved cursor, is counted in
`RunMetrics.quarantined`, and is logged once per run. Both bundled state
managers store each record's attempts and last error, truncated to 4,096
characters, and marking a record processed clears them.

Attempts are only counted from pages that processed a record, or from stalled
pages that a later page of the same run cleared. A page on which every record
fails says nothing about the records: during an outage or with a rejected API
key, every record fails, the run aborts (R5, R6), and no attempt is counted.

This has one limit. A record that fails on a page with no other relevant
record stalls that page. If the listing continues, a later page that processes
a record clears the stall and the attempt is counted. If that page is the last
page of the listing, the run aborts and nothing is counted, so such a record
reaches quarantine only in a run where the listing continues past it.

Pass `max_attempts=None` to count nothing and retry every failed record on
every run, as 0.4 did. A custom state manager that does not override
`record_failure` and `failure_counts` never quarantines.

## Newest-first listings

The arXiv extractor lists the newest submissions first, and the PubMed
extractor sorts newest first by default, so new papers push older ones to
higher offsets. A run that resumes from the saved offset keeps
working backwards through older papers and never sees the new ones. Pass
`newest_first=True` to pick up both:

```python
await pipeline.run(query="all:galaxy", total_limit=500, newest_first=True)
```

Such a run pages from offset 0 until it has passed the records the previous
run saw at the top of the listing. How far those records have moved is the
number of new submissions, so the saved offset has moved down by the same
number. The run jumps to the page just before that offset and checks that the
records last seen there are still on it. If they are, the papers in between
were settled by earlier runs and aren't listed again, and paging continues.

- **First run in this mode:** there is nothing saved to look for yet, so it
  scans from offset 0, skipping processed records by id, and saves the head of
  the listing for the next run.
- **Failures near the top:** the head the next run looks for is taken from the
  page where a record failed, so that run pages at least that far and revisits
  it.
- **Entries removed or reordered:** when the records before the saved offset
  aren't where they should be, the run pages on from the top instead of
  skipping, and logs `Records last seen before the saved offset have moved`.
- **Saved head no longer listed:** the run keeps paging to the end of the
  listing, which is a full rescan, and saves the new head.

A typical run with new papers costs two or three listing requests at the top,
one to check the saved offset, and the requests for the backlog. The records
it relies on are saved as `head_ids`, `head_offset`, and `tail_ids` in
`PipelineMetadata`, by both state backends. `newest_first` needs an extractor
that pages by offset (`OffsetListing`), and `start_index` can't be combined
with it.

Without `newest_first`, pass `start_index=0` to rescan a listing from its
first page, for example one whose order has shifted: processed records are skipped by id, so a rescan costs listing
requests (each preceded by the extractor's `sleep_before_search` delay) but
reprocesses nothing.

## What happens when something fails

| Situation | Behavior |
|-----------|----------|
| Listing request still fails after retries | `run()` raises `PipelineAborted` (cause: `UpstreamError`) |
| Source rejects the listing request, e.g. arXiv answers `400` | `run()` raises `PipelineAborted` (cause: `ExtractionError`) |
| Listing payload can't be parsed | `run()` raises `PipelineAborted` (cause: `MalformedResponseError`) |
| Listing is valid but has no entries, or a page has no next cursor | `run()` returns the count normally |
| The source stops at its result cap | `run()` returns the count normally; the next run starts from the first page |
| The source rejects a saved cursor (`StaleCursorError`) | the listing restarts from the first page; a second rejection in the run raises `PipelineAborted` |
| Listing page holds only already-processed or quarantined records | paging continues with the next page |
| One record raises, e.g. a transient full-text failure | logged through `logger`; record left unmarked; saved cursor held at its page; the attempt counted; other records continue |
| Records on one page fail and none on it is processed, but a later page processes a record | paging continues; the failed records stay unmarked for the next run |
| Records fail with none processed on a second page since the last page that processed a record, or on the last page of the listing, e.g. a rejected API key or an unreadable CSV | `run()` raises `PipelineAborted` (cause: the last record's error) |
| A shutdown is requested through `shutdown` | `run()` raises `PipelineInterrupted`; see [Graceful shutdown](shutdown.md) |
| arXiv reports the LaTeX and PDF as unavailable (e.g. 404), or neither can be parsed | full text falls back to the abstract |
| arXiv serves a single gzipped `.tex` file or a PDF as the e-print | the TeX is read, or the PDF is used instead |
| LLM call fails inside `AsyncLLMRelevanceFilter`, or its verdict is unclear | returns **`True`**; with `default_on_error=False`, `LLMError` propagates: logged, record left unmarked and retried on the next run |
| Record has an empty abstract | relevance filters return `default_on_empty_abstract` (**`True`**) |
| LLM call fails inside `AsyncLLMEntityExtractor`, its completion is empty, it has several keys and none is `result_key`, or its entity list is malformed | `LLMError` propagates: logged, record left unmarked and retried on the next run |
| Record has a missing or blank `record_id` | skipped and logged, since it can't be tracked as processed |

## Exceptions

All library exceptions derive from `SciEtlError`: `ExtractionError`
(`UpstreamError`, `MalformedResponseError`), `ParsingError`, `LLMError`,
`LLMCacheError`, `EmbeddingError`, `EmbeddingStoreError`, `SearchError`
(`SearchQueryError`, `SearchStoreError`), `StateStoreError`,
`ConfigurationError`, and `PipelineAborted` (`PipelineInterrupted`).
`ExtractionError` also has `StaleCursorError`. All of them can be imported from
`sci_etl_core`. The bundled parsers raise `ParsingError`
for bytes they can't read; a custom `Parser` should do the same, so
`AsyncArxivExtractor` moves on to its next source instead of failing the
record.
