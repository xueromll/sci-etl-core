# Logging

!!! warning "Deprecated in 0.5"
    Every `logger=` argument and `configure_logging` are deprecated and emit a
    `PendingDeprecationWarning`, since there is nothing to migrate to before
    0.6.0; they keep working through 0.5.x. In 0.6.0 each
    module logs through the standard `logging` module under the
    `sci_etl_core` logger, and the library stops configuring logging, so the
    application configures handlers itself, for example with
    `logging.basicConfig`. The progress events in
    [Observability](observability.md) remain the structured channel.

`configure_logging(name, log_file, level=logging.INFO)` returns a
`logging.Logger` that writes to a file and to stdout, creating the file's
folder if it doesn't exist. Calling it again with the same name, file, and
level returns the same logger; a different file or level replaces the handlers
it installed.

Components take a plain `logger` callable, so pass a bound method:

```python
from sci_etl_core import configure_logging

log = configure_logging("my_pipeline", "pipeline.log")
```

For example, `AsyncETLPipeline(..., logger=log.warning)` logs record failures
as warnings, and `AsyncArxivExtractor(..., logger=log.info)` logs retries as
information.
