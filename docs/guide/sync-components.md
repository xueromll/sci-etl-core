# Synchronous components

To reuse blocking implementations, subclass the synchronous interfaces and
wrap each object in its adapter. The result can be passed to either pipeline:

| Sync interface | Adapter | Where the calls run |
|----------------|---------|---------------------|
| `Extractor` | `SyncExtractorAdapter` | `fetch_full_text` in a worker thread; `search` and `parse_listing` on the event loop, between pages |
| `RelevanceFilter` | `SyncRelevanceFilterAdapter` | worker thread |
| `EntityExtractor` | `SyncEntityExtractorAdapter` | worker thread |
| `LLMClient` | `SyncLLMClientAdapter` | worker thread |
| `Exporter` | `SyncExporterAdapter` | on the event loop, so exports never interleave |
| `StateManager` | `SyncStateManagerAdapter` | on the event loop, so updates are never lost |

```python
import json

from sci_etl_core import Exporter, SyncExporterAdapter


class JsonLinesExporter(Exporter):
    def export(self, data, destination):
        with open(destination, "a", encoding="utf-8") as handle:
            for row in data:
                handle.write(json.dumps(row) + "\n")


exporter = SyncExporterAdapter(JsonLinesExporter())
```

Pass the adapter wherever the pipeline expects the async interface, for
example `AsyncETLPipeline(..., exporter=exporter)`.

Calls that run on the event loop block it while they run: a slow exporter or
state manager stalls every record in flight. Keep those calls fast, or
implement the async interface instead.
