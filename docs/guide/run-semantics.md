# Run semantics

`AsyncETLPipeline.run` makes the guarantees below. Each one is numbered, and
each has a test in `tests/semantics/test_run_rules.py` whose name starts with
the rule's number, such as `test_r1_cursor_waits_for_settled_page`. Changing a
rule is a breaking change: it changes the rule's test, and it gets a
[MIGRATION.md](../project/migration.md) entry.

A record is **settled** once it is processed, marked irrelevant, or skipped as
quarantined. A record is **durable** once the exporter holds its entities
durably (R20). A page is **stalled** when records on it failed and none was
processed, or when the exporter's `flush` failed for it. A page **ends the listing** when it has no next cursor, has no
entries, or is truncated.

| Rule | Guarantee | Tests | Source |
|------|-----------|-------|--------|
| R1 | The saved cursor never moves forward past a page with an unsettled record: once a record fails, is deferred by `total_limit`, or was written but not made durable by a failed `flush`, the cursor stays at the start of that page for the rest of the run. Resetting it to the first page (R15, R16) is not moving forward. A record skipped as quarantined counts as settled (R18). | `test_r1_*` | `_listing_position.py:46-57` |
| R2 | `total_limit` is exact. A relevant record reserves a slot before its full text is fetched, and a record that fails releases its slot for another record. | `test_r2_*` | `pipeline_async.py:81-98`, `:802-821` |
| R3 | An irrelevant record is marked processed at once, without fetching its full text. | `test_r3_*` | `pipeline_async.py:805-807` |
| R4 | A memory-ingest exception in `MEMORY_FAULTS` is logged and counted in `RunMetrics.memory_faults`, and the record's entities are still exported. | `test_r4_*` | `pipeline_async.py:832-840` |
| R5 | Two stalled pages, with no page that processed a record between them, abort the run with `PipelineAborted`. A single stalled page is tolerated. Records skipped as processed or quarantined make a page neither stalled nor processing. A page whose exporter `flush` failed is stalled (R21). | `test_r5_*` | `pipeline_async.py:46`, `:562-574` |
| R6 | A stalled page that ends the listing, or is followed by a page that does, aborts the run before the end is saved. This takes precedence over R15. | `test_r6_*` | `pipeline_async.py:575-576` |
| R7 | A page with no next cursor, or with no entries, ends the run `"completed"` once the page settles. An `OffsetListing` then saves the offset past the last entry, so entries appended later are found by the next run; any other extractor saves no cursor, so the next run starts from the first page. | `test_r7_*` | `_listing_position.py:46-75` |
| R8 | A page made up entirely of already-processed records is not the end; paging moves past it. | `test_r8_*` | `pipeline_async.py:601-613` |
| R9 | A shutdown request finishes the records in flight, flushes the exporter, marks the records that flush made durable, leaves the rest of the page for the next run, keeps the saved cursor before that page, closes the exporter, flushes state, and raises `PipelineInterrupted`. | `test_r9_*` | `pipeline_async.py:515-531`, `:767-785`, `:803-804` |
| R10 | The exporter is flushed and closed, and then state is flushed, however the run ends. A fault in either after the run failed is logged, so it never hides the original error; an exporter close fault after a successful run is raised once state is flushed. | `test_r10_*` | `pipeline_async.py:451-469`, `:698-724` |
| R11 | A record whose `record_id` is missing or blank is skipped, logged, and reported as a `RecordFinished` event with outcome `"skipped"`. | `test_r11_*` | `pipeline_async.py:740-745` |
| R12 | `sleep_between` is waited between pages, never after the page that reaches `total_limit` or ends the listing. | `test_r12_*` | `pipeline_async.py:582-587` |
| R13 | A listing page that cannot be fetched or parsed aborts the run with `PipelineAborted` carrying the count processed so far. | `test_r13_*` | `pipeline_async.py:726-734` |
| R14 | For an `OffsetListing`, a `newest_first=True` run pages from offset 0 until it finds the records saved at the head of the listing, then continues from the saved offset moved down by the number of new entries. Each offset cursor comes from `cursor_for_offset`, and the listed ids come from the page's records, so each page is fetched and parsed once. | `test_r14_*` | `_listing_position.py:77-134` |
| R15 | A truncated page that is not a stall page ends the run `"completed"`, reports the truncation in `RunMetrics.listing_truncated`, `PageFetched.truncated`, and one log line per run, resets the saved cursor to the first page even when a page did not settle, and sets `PipelineMetadata.truncated`. The flag is cleared by the first run that reaches the end of the listing without a cap; a run that aborts, is interrupted, or reaches `total_limit` leaves it unchanged. | `test_r15_*` | `pipeline_async.py:544-548`, `:578-581` |
| R16 | A `StaleCursorError` restarts the listing from the first page once per run; a second one in the same run raises `PipelineAborted`. | `test_r16_*` | `pipeline_async.py:520-529` |
| R17 | `newest_first=True`, or a `start_index` above 0, with an extractor that is not an `OffsetListing` raises `ValueError` before any request. | `test_r17_*` | `pipeline_async.py:443-446` |
| R18 | With `max_attempts` set, failures are counted through `record_failure` only from pages that processed a record, or from stalled pages that a later page of the same run cleared; failures held by a stalled page that is never cleared are discarded. A listed record whose counted attempts reach `max_attempts` is skipped as quarantined, counted once per run in `RunMetrics.quarantined`, and logged once. No record is quarantined in the run in which its last attempt failed. | `test_r18_*` | `pipeline_async.py:124-141`, `:564-567`, `:601-631` |
| R19 | A record is settled only on an answer. A relevance fault in a filter built with `default_on_error=False`, and an LLM response that holds no entity list, because the completion is empty or has several keys and none is `result_key`, fail the record: it stays unmarked, its attempt is counted under R18, and it is retried on the next run. | `test_r19_*` | `llm/openai_compatible_async.py:206-207`, `llm/extraction_async.py:281-288`, `llm/relevance_async.py:96-109`, `pipeline_async.py:802-821` |
| R20 | A record is marked processed only once its entities are durable: right after `write` on an exporter with `durable_writes = True`, and after the page's `flush` otherwise. A crash between `write` and `flush` repeats the record on the next run and loses none. | `test_r20_*` | `pipeline_async.py:767-785`, `:814-817` |
| R21 | A `write` fault fails the record and counts one attempt under R18. A `flush` fault leaves the records written since the last successful flush unsettled, counts no attempt against them, and makes the page a stalled page, so two failed flushes in a row abort the run under R5. | `test_r21_*` | `pipeline_async.py:773-781`, `:814` |
| R22 | A fault in the exporter's `open` aborts the run with `PipelineAborted` before any listing request. | `test_r22_*` | `pipeline_async.py:453-457`, `:704-708` |
| R23 | Every processed record is written to the exporter, including one with no entities; an irrelevant record is not. | `test_r23_*` | `pipeline_async.py:805-814` |

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
