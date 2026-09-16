# Graceful shutdown

`ShutdownSignal` turns SIGINT/SIGTERM into a flag you can await. The pipeline
doesn't use it on its own, so run the pipeline as a task alongside it:

```python
import asyncio

from sci_etl_core.signals import ShutdownSignal


async def run_until_signalled(pipeline, state_manager, **run_kwargs):
    shutdown = ShutdownSignal(logger=print)
    with shutdown.guard():
        run = asyncio.create_task(pipeline.run(**run_kwargs))
        stop = asyncio.create_task(shutdown.wait())
        done, _ = await asyncio.wait({run, stop}, return_when=asyncio.FIRST_COMPLETED)
        for task in (run, stop):
            if task not in done:
                task.cancel()
        await asyncio.gather(run, stop, return_exceptions=True)
    await state_manager.flush()
    return None if run.cancelled() else run.result()
```

- **First signal:** sets the flag. Cancelled in-flight records stay unmarked
  and are retried on the next run.
- **Second signal:** restores the previous handler and terminates immediately.
- **Where it works:** call `guard()` from async code on the main thread; on any
  other thread it logs a message and installs nothing. That means it can't be
  used through `ETLPipeline`, whose loop runs on a background thread.
