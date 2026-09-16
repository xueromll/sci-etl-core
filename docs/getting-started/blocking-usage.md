# Blocking usage

`ETLPipeline` is the only synchronous class. It accepts the same arguments as
`AsyncETLPipeline` — including the same **async** collaborators — plus
`run_timeout`:

```python
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvUpsertExporter,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    ETLPipeline,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.processors import DefaultKeyNormalizer

RELEVANCE_PROMPT = (
    "Decide whether the paper reports measurements of galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "Extract every measured object from the paper. Reply with JSON: "
    '{"items": [{"name": "...", "value_a": 0.0, "value_b": 0.0}]}.'
)

client = build_async_client()
llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
)

with ETLPipeline(
    extractor=AsyncArxivExtractor(
        client=client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
    ),
    relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
    entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
    exporter=AsyncCsvUpsertExporter(
        key_column="name",
        value_columns=["value_a", "value_b"],
        normalizer=DefaultKeyNormalizer(),
    ),
    state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
    destination="results.csv",
    closeables=[client, llm],
    run_timeout=3600,
) as pipeline:
    try:
        processed = pipeline.run(query="all:galaxy", total_limit=50)
    except PipelineAborted as exc:
        processed = exc.partial_count

print(f"Processed {processed} relevant records")
```

- **There are no blocking versions of individual components.** To call an
  extractor, client, or exporter directly from synchronous code, wrap the calls
  in a coroutine and run it with `asyncio.run`. To plug your own blocking
  implementations into a pipeline, see
  [Synchronous components](../guide/sync-components.md).
- **`run_timeout`** is in seconds and unlimited by default. When it expires,
  the run is cancelled and `TimeoutError` is raised.
- **Event loop.** `ETLPipeline` runs the pipeline on a shared background
  event-loop thread. It works from plain scripts, and also when called from
  inside a running event loop (for example a notebook). It still blocks the
  calling thread until the run finishes, so in async code await
  `AsyncETLPipeline` instead. Once an `ETLPipeline` has used a collaborator,
  that collaborator belongs to the background loop — don't also use it from
  your own event loop.
- **`with ETLPipeline(...)`** closes `closeables` on exit, allowing up to 30
  seconds per resource.
