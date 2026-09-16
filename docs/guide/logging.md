# Logging

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
