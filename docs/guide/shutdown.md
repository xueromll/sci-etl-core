# Graceful shutdown

Pass a `ShutdownSignal` to the pipeline, and SIGINT (Ctrl+C) or SIGTERM stops a
run cleanly:

```python
from sci_etl_core import AsyncETLPipeline, PipelineInterrupted
from sci_etl_core.signals import ShutdownSignal

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
    destination="results.csv",
    shutdown=ShutdownSignal(),
)

try:
    count = await pipeline.run(query="all:galaxy", total_limit=500)
except PipelineInterrupted as stopped:
    print(f"Stopped after {stopped.partial_count} records; the next run picks up the rest")
```

The pipeline installs the signal handlers for the duration of each `run()` and
puts the previous handlers back afterwards.

- **First signal:** no new record starts. Records already in flight finish
  and are marked processed; records that hadn't started stay unmarked for the
  next run. A pending listing request or the wait between pages is cancelled
  at once. The saved cursor doesn't move past the page that was cut short.
  State is flushed, and `run()` raises `PipelineInterrupted` carrying the
  number of records processed.
- **Second signal:** restores the previous handler and terminates immediately.
- **Programmatic stop:** `shutdown.request()` stops the run the same way, from
  a web handler or a test for example.

`PipelineInterrupted` subclasses `PipelineAborted`, so an existing
`except PipelineAborted` still catches it. Catch `PipelineInterrupted` first
when an interrupted run should exit differently from a failed one.

## The synchronous pipeline

`ETLPipeline` takes the same `shutdown` argument. Its work runs on a background
event loop, so the handlers are installed on the thread that calls `run()`
and forward the request to that loop. Call `run()` from the main thread, since
only the main thread receives signals:

```python
from sci_etl_core import ETLPipeline
from sci_etl_core.signals import ShutdownSignal

with ETLPipeline(..., shutdown=ShutdownSignal()) as pipeline:
    pipeline.run(query="all:galaxy", total_limit=500)
```

## Flushing state

Every run ends with the state manager's `flush()`, however it ends: completed,
aborted, interrupted, or cancelled. `AsyncSqliteStateManager` checkpoints its
write-ahead log there. When the run itself failed, a flush failure is logged
instead of raised, so it doesn't hide the original error.

## Handlers of your own

`shutdown.guard()` installs the handlers for a block of your own code. Guards
nest, so a pipeline given the same signal inside that block leaves your
handlers in place when its run ends. Handlers are only installed from the main
thread; elsewhere `guard()` logs a message and installs nothing, and
`request()` still works.
