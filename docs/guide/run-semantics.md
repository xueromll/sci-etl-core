# Run semantics

`AsyncETLPipeline.run` makes the guarantees below. Each one is numbered, and
each has a test in `tests/semantics/test_run_rules.py` whose name starts with
the rule's number, such as `test_r1_cursor_waits_for_settled_page`. Changing a
rule is a breaking change: it changes the rule's test, and it gets a
[MIGRATION.md](../project/migration.md) entry.

A record is **settled** once it is processed, marked irrelevant, or skipped as
quarantined. A page is **stalled** when records on it failed and none was
processed. A page **ends the listing** when it has no next cursor, has no
entries, or is truncated.

| Rule | Guarantee | Tests | Source |
|------|-----------|-------|--------|
| R1 | The saved cursor never moves forward past a page with an unsettled record: once a record fails, or is deferred by `total_limit`, the cursor stays at the start of that page for the rest of the run. Resetting it to the first page (R15, R16) is not moving forward. A record skipped as quarantined counts as settled (R18). | `test_r1_*` | `_listing_position.py:44-55` |
| R2 | `total_limit` is exact. A relevant record reserves a slot before its full text is fetched, and a record that fails releases its slot for another record. | `test_r2_*` | `pipeline_async.py:66-82`, `:728-746` |
| R3 | An irrelevant record is marked processed at once, without fetching its full text. | `test_r3_*` | `pipeline_async.py:731-733` |
| R4 | A memory-ingest exception in `MEMORY_FAULTS` is logged and counted in `RunMetrics.memory_faults`, and the record's entities are still exported. | `test_r4_*` | `pipeline_async.py:763-765` |
| R5 | Two stalled pages, with no page that processed a record between them, abort the run with `PipelineAborted`. A single stalled page is tolerated. Records skipped as processed or quarantined make a page neither stalled nor processing. | `test_r5_*` | `pipeline_async.py:44`, `:539-544` |
| R6 | A stalled page that ends the listing, or is followed by a page that does, aborts the run before the end is saved. This takes precedence over R15. | `test_r6_*` | `pipeline_async.py:545-546` |
| R7 | A page with no next cursor, or with no entries, ends the run `"completed"` once the page settles. An `OffsetListing` then saves the offset past the last entry, so entries appended later are found by the next run; any other extractor saves no cursor, so the next run starts from the first page. | `test_r7_*` | `_listing_position.py:44-73` |
| R8 | A page made up entirely of already-processed records is not the end; paging moves past it. | `test_r8_*` | `pipeline_async.py:571-583` |
| R9 | A shutdown request finishes the records in flight, leaves the rest of the page for the next run, keeps the saved cursor before that page, and raises `PipelineInterrupted`. | `test_r9_*` | `pipeline_async.py:491-505`, `:729-730` |
| R10 | State is flushed however the run ends. A flush fault after the run failed is logged, so it never hides the original error. | `test_r10_*` | `pipeline_async.py:443-445`, `:668-672` |
| R11 | A record whose `record_id` is missing or blank is skipped, logged, and reported as a `RecordFinished` event with outcome `"skipped"`. | `test_r11_*` | `pipeline_async.py:694-697` |
| R12 | `sleep_between` is waited between pages, never after the page that reaches `total_limit` or ends the listing. | `test_r12_*` | `pipeline_async.py:552-557` |
| R13 | A listing page that cannot be fetched or parsed aborts the run with `PipelineAborted` carrying the count processed so far. | `test_r13_*` | `pipeline_async.py:678-686` |
| R14 | For an `OffsetListing`, a `newest_first=True` run pages from offset 0 until it finds the records saved at the head of the listing, then continues from the saved offset moved down by the number of new entries. Each offset cursor comes from `cursor_for_offset`, and the listed ids come from the page's records, so each page is fetched and parsed once. | `test_r14_*` | `_listing_position.py:75-135` |
| R15 | A truncated page that is not a stall page ends the run `"completed"`, reports the truncation in `RunMetrics.listing_truncated`, `PageFetched.truncated`, and one log line per run, resets the saved cursor to the first page even when a page did not settle, and sets `PipelineMetadata.truncated`. The flag is cleared by the first run that reaches the end of the listing without a cap; a run that aborts, is interrupted, or reaches `total_limit` leaves it unchanged. | `test_r15_*` | `pipeline_async.py:518-520`, `:548-551` |
| R16 | A `StaleCursorError` restarts the listing from the first page once per run; a second one in the same run raises `PipelineAborted`. | `test_r16_*` | `pipeline_async.py:496-503` |
| R17 | `newest_first=True`, or a `start_index` above 0, with an extractor that is not an `OffsetListing` raises `ValueError` before any request. | `test_r17_*` | `pipeline_async.py:428-431` |
| R18 | With `max_attempts` set, failures are counted through `record_failure` only from pages that processed a record, or from stalled pages that a later page of the same run cleared; failures held by a stalled page that is never cleared are discarded. A listed record whose counted attempts reach `max_attempts` is skipped as quarantined, counted once per run in `RunMetrics.quarantined`, and logged once. No record is quarantined in the run in which its last attempt failed. | `test_r18_*` | `pipeline_async.py:101-121`, `:535-542`, `:571-594` |

The source column cites the code behind each rule. A change that moves that
code updates its citation here.

## Capped listings

PubMed serves the first 9,999 results of a query and Semantic Scholar's
relevance search the first 1,000. Their extractors mark the page that reaches
the cap as truncated, and R15 applies: the run completes, and the next run
pages the reachable results again. Processed records are skipped by id, so the
rescan costs listing requests, not LLM calls: at `page_size=100`, up to 10
requests for Semantic Scholar and 100 for PubMed. The rescan also finds
records that entered the reachable window since the last run, which matters
for a listing sorted by relevance. To avoid the rescan, narrow the query, for
example by date range. OpenAlex is not capped: `AsyncOpenAlexExtractor` pages
with OpenAlex cursors.
