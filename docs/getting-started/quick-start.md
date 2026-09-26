# Quick start

This example searches arXiv, asks an LLM which papers are relevant, extracts
measurements from their full text, and upserts them into a CSV. It needs the
`async`, `llm`, and `pdf` extras, and reads the API key from the `LLM_API_KEY`
environment variable, so the key never appears in source code. To load it from
a `.env` file instead, see [Configuration](configuration.md).

```python
import asyncio
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvUpsertExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
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


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(
        api_key=os.environ["LLM_API_KEY"],
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(
            client=client,
            pdf_parser=PdfPlumberParser(),
            latex_parser=LatexTarballParser(),
        ),
        relevance_filter=AsyncLLMRelevanceFilter(
            llm_client=llm, system_prompt=RELEVANCE_PROMPT
        ),
        entity_extractor=AsyncLLMEntityExtractor(
            llm_client=llm, system_prompt=EXTRACTION_PROMPT
        ),
        exporter=AsyncCsvUpsertExporter(
            key_column="name",
            value_columns=["value_a", "value_b"],
            normalizer=DefaultKeyNormalizer(),
        ),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        destination="results.csv",
        max_concurrency=4,
        closeables=[client, llm],
    )

    async with pipeline:
        try:
            processed = await pipeline.run("all:galaxy", total_limit=50)
        except PipelineAborted as exc:
            print(f"Stopped early after {exc.partial_count} records: {exc}")
            return
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

## What a run does

1. Fetches a listing page (`page_size` records, default 100) at the cursor
   saved by the state manager (or from the first page with `start_index=0`),
   and skips records already processed. A page that holds only processed
   records is passed over, not treated as the end of the data.
2. For each remaining record, with at most `max_concurrency` in flight:
   relevance filter → full-text fetch → optional memory ingest → entity
   extraction → export → mark processed. Irrelevant records are marked
   processed without fetching full text. Records whose `record_id` is missing
   or blank can't be tracked, so they are skipped and logged.
3. Saves the listing cursor and repeats until `total_limit` relevant records
   are processed or the listing ends, waiting `sleep_between` seconds
   (default 0) before each further page. The cursor only moves past pages
   whose records were all settled, and a record that failed in 3 runs is
   skipped as quarantined; see [State, resuming, and errors](../guide/state.md).

`total_limit` counts **relevant** records only, is never exceeded, and defaults
to `page_size`. Every argument of `run()` after the query is keyword-only.
`max_concurrency` and `page_size` must be at least 1 and `total_limit` must not
be negative; other values raise `ValueError` before any request is made.
`AsyncArxivExtractor` also waits `sleep_before_search` seconds (default 3)
before every listing request, to respect arXiv's rate limits.

On exit, `async with pipeline` awaits `aclose()` on every entry in
`closeables` that has one — the HTTP client, the LLM client, and any
`AsyncSqliteStateManager`, `AsyncSqliteEmbeddingStore`, or
`AsyncSqliteFts5Store` you use.

## Prompts must ask for JSON

`AsyncOpenAICompatibleClient` requests JSON mode
(`response_format={"type": "json_object"}`), and OpenAI's API rejects JSON-mode
requests whose messages never mention "JSON". The response shapes the library
reads:

- `AsyncLLMRelevanceFilter` reads the `relevant` key. It accepts a boolean,
  `0`/`1`, or the strings `"true"`, `"false"`, `"yes"`, `"no"`, `"1"`, and
  `"0"` in any case. Anything else, including a missing key, is treated as an
  error: the record passes, or, with `default_on_error=False`, the filter
  raises `LLMError` and the record is retried.
- `AsyncLLMEntityExtractor` reads the list under `result_key` (default
  `"items"`), or the only value if the response has exactly one key. The list
  must hold objects; `null` means no entities and a lone object counts as one.
  Any other value there raises `LLMError`, so the record is retried. An empty
  completion, and a response with several keys but no `result_key`, raise
  `LLMError` too, so name the key in the prompt.
- `AsyncCsvUpsertExporter` takes each item's `key_column` value as the row key,
  so the extraction prompt must ask for that field.

## Next steps

- Run the same pipeline from synchronous code with
  [`ETLPipeline`](blocking-usage.md).
- Load the settings from YAML and `.env` with
  [typed configuration](configuration.md).
- Clean and plot the CSV with the
  [post-processing steps](../guide/post-processing.md).
