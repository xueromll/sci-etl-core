# Progress events and metrics

Every pipeline run collects metrics, and can report its progress as it goes.

## Run metrics

`pipeline.last_run_metrics` returns a `RunMetrics` for the most recent run,
however it ended:

```python
from sci_etl_core import AsyncETLPipeline

pipeline = AsyncETLPipeline(..., usage_sources=[llm, embedder])
try:
    await pipeline.run(query="all:galaxy", total_limit=200, newest_first=True)
finally:
    metrics = pipeline.last_run_metrics
    print(
        f"{metrics.outcome}: {metrics.processed} processed, {metrics.irrelevant} irrelevant, "
        f"{metrics.failed} failed in {metrics.duration_seconds:.0f} s"
    )
```

| Field | Meaning |
|-------|---------|
| `pages`, `listed` | Listing pages fetched and the entries they held |
| `processed`, `irrelevant`, `deferred`, `failed`, `skipped` | Records by outcome; `deferred` records wait for the next run because of `total_limit` or a shutdown, and `skipped` records had no id |
| `entities_exported` | Entities handed to the exporter |
| `memory_faults` | Memory ingest faults that were logged without failing their record |
| `duration_seconds` | Wall time of the run |
| `token_usage` | Tokens the `usage_sources` used during this run, or `None` without sources |
| `outcome` | `completed`, `aborted`, `interrupted`, `cancelled`, or `failed` |

`usage_sources` takes any objects with a `usage` property, such as
`AsyncOpenAICompatibleClient`, `AsyncOpenAIEmbedder`, or `CachingLLMClient`.
Their usage before the run is subtracted, so a client shared across runs
reports each run separately.

## Progress events

Pass `on_event` to receive typed events from `sci_etl_core.observability` as
the run progresses:

```python
from sci_etl_core.observability import PageFinished, RecordFinished, RunFinished


def report(event):
    if isinstance(event, RecordFinished) and event.outcome == "failed":
        print(f"{event.record_id} failed after {event.duration_seconds:.1f} s: {event.error!r}")
    elif isinstance(event, PageFinished):
        print(f"page at {event.offset}: {event.metrics.processed} processed so far")
    elif isinstance(event, RunFinished):
        print(f"run {event.metrics.outcome}")


pipeline = AsyncETLPipeline(..., on_event=report)
```

| Event | When |
|-------|------|
| `RunStarted(query, start_index, total_limit, newest_first)` | Before the first listing request |
| `PageFetched(offset, entries, new_records)` | A listing page arrived; `new_records` aren't processed yet |
| `RecordFinished(record_id, title, outcome, duration_seconds, entities, error)` | A record left the pipeline for this run |
| `PageFinished(offset, duration_seconds, metrics)` | Every record of a page finished; `metrics` is the run so far |
| `RunFinished(metrics)` | The run ended, however it ended |

The handler runs on the event loop, so keep it quick: hand slow work, such as
a network call, to a queue. An exception it raises is logged as
`Event handler failed: ...` and never stops the run. `ETLPipeline` takes the
same arguments and exposes `last_run_metrics` too.
