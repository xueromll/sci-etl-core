# Run semantics

`AsyncETLPipeline.run` makes the guarantees below. Each one is numbered, and
each has a test in `tests/semantics/test_run_rules.py` whose name starts with
the rule's number, such as `test_r1_offset_waits_for_settled_page`. Changing a
rule is a breaking change: it changes the rule's test, and it gets a
[MIGRATION.md](../project/migration.md) entry.

A record is **settled** once it is processed, or marked irrelevant. A page is
**stalled** when records on it failed and none was processed.

| Rule | Guarantee | Tests | Source |
|------|-----------|-------|--------|
| R1 | The saved offset moves only past pages whose every record settled. Once a record fails, or is deferred by `total_limit`, the offset stays at the start of that page for the rest of the run. | `test_r1_*` | `pipeline_async.py:417-421` |
| R2 | `total_limit` is exact. A relevant record reserves a slot before its full text is fetched, and a record that fails releases its slot for another record. | `test_r2_*` | `pipeline_async.py:59-76`, `:584-601` |
| R3 | An irrelevant record is marked processed at once, without fetching its full text. | `test_r3_*` | `pipeline_async.py:586-588` |
| R4 | A memory-ingest exception in `MEMORY_FAULTS` is logged and counted in `RunMetrics.memory_faults`, and the record's entities are still exported. | `test_r4_*` | `pipeline_async.py:603-620` |
| R5 | Two stalled pages, with no page that processed a record between them, abort the run with `PipelineAborted`. A single stalled page is tolerated. | `test_r5_*` | `pipeline_async.py:41`, `:401-407` |
| R6 | A stalled page followed by the end of the listing aborts the run. | `test_r6_*` | `pipeline_async.py:426-427` |
| R7 | An empty listing is the only data-driven clean end. A fetch that returns no payload aborts the run instead. | `test_r7_*` | `pipeline_async.py:383-385` |
| R8 | A page made up entirely of already-processed records is not the end; paging moves past it. | `test_r8_*` | `pipeline_async.py:379-383` |
| R9 | A shutdown request finishes the records in flight, leaves the rest of the page for the next run, keeps the saved offset before that page, and raises `PipelineInterrupted`. | `test_r9_*` | `pipeline_async.py:372-378`, `:584` |
| R10 | State is flushed however the run ends. A flush fault after the run failed is logged, so it never hides the original error. | `test_r10_*` | `pipeline_async.py:325-334`, `:494-498` |
| R11 | A record whose `record_id` is missing or blank is skipped, logged, and reported as a `RecordFinished` event with outcome `"skipped"`. | `test_r11_*` | `pipeline_async.py:531-536` |
| R12 | `sleep_between` is waited between pages, never after the page that reaches `total_limit`. | `test_r12_*` | `pipeline_async.py:423-424` |
| R13 | A listing that cannot be fetched or parsed aborts the run with `PipelineAborted` carrying the count processed so far. | `test_r13_*` | `pipeline_async.py:508-525` |
| R14 | A `newest_first=True` run pages from offset 0 until it finds the records saved at the head of the listing, then continues from the saved offset moved down by the number of new entries. | `test_r14_*` | `pipeline_async.py:360-362`, `:409-416` |

The source column cites the code behind each rule. A change that moves that
code updates its citation here.

## Known limitation: capped listings

OpenAlex and PubMed serve at most 10,000 results for a query, and Semantic
Scholar serves 1,000. Past that cap, the extractor returns an empty listing,
which the pipeline reads as the end of the data (R7). A run without
`newest_first` ends `"completed"` with its offset saved at the cap, so every
later run with the same query ends at once. `test_characterization_capped_listing_pins_every_later_run_at_the_cap`
records this behavior. Until it changes, narrow a query that could reach a
source's cap, for example by date range, or pass `start_index=0` to rescan.
