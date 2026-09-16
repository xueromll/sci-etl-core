# State, resuming, and errors

## State backends

Two state backends ship with the library:

- **`AsyncFileStateManager(processed_ids_file, metadata_file)`** stores one
  processed id per line plus a JSON metadata file. It holds OS-level file locks
  and writes metadata atomically.
- **`AsyncSqliteStateManager(database_path)`** uses a WAL-mode SQLite
  database. Add it to `closeables` so its connection is closed. Its `flush()`
  checkpoints the WAL.

## Resuming

Each run starts at the saved `last_start_index` and skips ids that were
already processed. The offset is saved after every page, but it only moves
past a page once every record on it is settled, meaning processed or marked
irrelevant. When a record fails, or is left over because `total_limit` was
reached, the offset stays at the start of that page for the rest of the run,
so the next run revisits it while skipping everything already processed.

Records are exported before they are marked processed, so a crash between the
two re-exports that record on the next run. `AsyncCsvUpsertExporter` absorbs
this; an appending exporter of your own should tolerate duplicates.

`AsyncFileStateManager` raises `OSError` when a state file exists but can't be
read, rather than treating it as empty. It rejects record ids that contain a
line boundary or have leading or trailing whitespace, since neither would read
back unchanged. Metadata content that isn't valid falls back to offset 0, which
only costs a rescan. Both backends record `last_run_at` as an ISO 8601
timestamp in UTC.

## Newest-first listings

The arXiv extractor lists the newest submissions first, and the PubMed and
OpenAlex extractors sort newest first by default, so new papers push older
ones to higher offsets. A run that resumes from the saved offset keeps
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
`PipelineMetadata`, by both state backends. `start_index` can't be combined
with `newest_first`.

Without `newest_first`, pass `start_index=0` to rescan a listing whose order
has shifted: processed records are skipped by id, so a rescan costs listing
requests (each preceded by the extractor's `sleep_before_search` delay) but
reprocesses nothing.

## What happens when something fails

| Situation | Behavior |
|-----------|----------|
| Listing request still fails after retries | `run()` raises `PipelineAborted` (cause: `UpstreamError`) |
| Source rejects the listing request, e.g. arXiv answers `400` | `run()` raises `PipelineAborted` (cause: `ExtractionError`) |
| Listing payload can't be parsed | `run()` raises `PipelineAborted` (cause: `MalformedResponseError`) |
| Listing is valid but has no entries | `run()` returns the count normally |
| Listing page holds only already-processed records | paging continues with the next page |
| One record raises, e.g. a transient full-text failure | logged through `logger`; record left unmarked; saved offset held at its page; other records continue |
| Records on one page fail and none on it is processed, but a later page processes a record | paging continues; the failed records stay unmarked for the next run |
| Records fail with none processed on a second page since the last page that processed a record, or on the last page of the listing, e.g. a rejected API key or an unreadable CSV | `run()` raises `PipelineAborted` (cause: the last record's error) |
| A shutdown is requested through `shutdown` | `run()` raises `PipelineInterrupted`; see [Graceful shutdown](shutdown.md) |
| arXiv reports the LaTeX and PDF as unavailable (e.g. 404), or neither can be parsed | full text falls back to the abstract |
| arXiv serves a single gzipped `.tex` file or a PDF as the e-print | the TeX is read, or the PDF is used instead |
| LLM call fails inside `AsyncLLMRelevanceFilter`, or its verdict is unclear | returns `default_on_error` (**`True`**) |
| Record has an empty abstract | relevance filters return `default_on_empty_abstract` (**`True`**) |
| LLM call fails inside `AsyncLLMEntityExtractor`, or its entity list is malformed | `LLMError` propagates: logged, record left unmarked and retried on the next run |
| Record has a missing or blank `record_id` | skipped and logged, since it can't be tracked as processed |

## Exceptions

All library exceptions derive from `SciEtlError`: `ExtractionError`
(`UpstreamError`, `MalformedResponseError`), `ParsingError`, `LLMError`,
`LLMCacheError`, `EmbeddingError`, `EmbeddingStoreError`, `SearchError`
(`SearchQueryError`, `SearchStoreError`), `ConfigurationError`, and
`PipelineAborted` (`PipelineInterrupted`). All of them can be imported from
`sci_etl_core`. The bundled parsers raise `ParsingError`
for bytes they can't read; a custom `Parser` should do the same, so
`AsyncArxivExtractor` moves on to its next source instead of failing the
record.
