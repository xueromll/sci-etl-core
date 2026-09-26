# Logging

Each sci-etl-core module logs through the standard `logging` module, under a
logger named after the module, such as `sci_etl_core.pipeline_async` or
`sci_etl_core.extractors.arxiv_async`. All of them sit under the
`sci_etl_core` logger. The library installs no handlers and sets no levels, so
nothing is printed until the application configures logging:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
logging.getLogger("sci_etl_core.extractors").setLevel(logging.WARNING)
```

The levels mean:

| Level | Used for |
|-------|----------|
| `ERROR` | A sink or store fault the run reports: an exporter `flush` or `aclose` failed, state could not be flushed, a resource could not be closed, an event handler raised |
| `WARNING` | Something that changes what the run produces or costs: a record failed or was skipped, a record was quarantined, a source stopped at its result cap or rejected a cursor, a memory backend failed, a download was unusable, a retry, a shutdown signal |
| `INFO` | Routine notes: an entity or claim was rejected by validation, where a `newest_first` run resumed |

Messages keep the wording earlier releases passed to `logger=` callables, such
as `Record processing failed: LLMError('...')`, so a filter or alert written
against them still matches.

The progress events in [Observability](observability.md) remain the
structured channel: count records, pages, and outcomes from the events, and
use logs for the reasons.
