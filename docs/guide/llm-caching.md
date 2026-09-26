# LLM response caching

Rerunning a pipeline after a crash, a prompt tweak elsewhere, or a change to
export code asks the LLM the same questions again. `CachingLLMClient` answers
repeated requests from a cache, so they cost no tokens and return at once:

```python
from sci_etl_core import (
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    AsyncSqliteLLMResponseCache,
    CachingLLMClient,
)

cache = AsyncSqliteLLMResponseCache("cache/llm.db")
llm = CachingLLMClient(AsyncOpenAICompatibleClient.from_config(config.llm), cache, logger=print)

relevance_filter = AsyncLLMRelevanceFilter(llm, relevance_prompt)
entity_extractor = AsyncLLMEntityExtractor(llm, extraction_prompt)
```

List the SQLite cache in the pipeline's `closeables` so its connection is
closed at the end of the run.

## How requests are matched

A request is keyed on the model name, the endpoint's `base_url`, the
temperature, and both prompts, hashed with SHA-256; the timeout isn't part of
the key. A changed system prompt, a changed paper text, a different model, a
different provider, or a different temperature is a miss.

`CachingLLMClient` reads `base_url` and `temperature` from the client it wraps.
`AsyncOpenAICompatibleClient` exposes both. A custom client without them is
keyed on the model and prompts only.

## What is cached

A request that failed is never cached, so it is sent again next time. A
response the library rejects isn't kept either:

- `AsyncLLMEntityExtractor` rejects a response that holds no entity list, or
  whose entity list isn't a list of objects.
- `AsyncLLMRelevanceFilter` rejects a response without a clear verdict.

Both call `invalidate` on the client, and `CachingLLMClient` deletes the
cached response, so the retry on the next run reaches the model instead of
replaying the same answer.

## Backends

- **`InMemoryLLMResponseCache(max_entries=None)`** lives as long as the process.
  With `max_entries`, the least recently used response is evicted once it's
  full.
- **`AsyncSqliteLLMResponseCache(path)`** keeps responses in a SQLite file
  between runs. `clear()` empties it and `count()` reports its size.

A custom backend, such as Redis, subclasses `AsyncLLMResponseCache` and
implements `get`, `set`, `delete`, and `clear`. A backend without `delete`
still works, but each rejected response stays cached and is logged as a cache
fault.

## When the cache fails

The cache never fails a completion. If reading or writing it raises, the error
is logged as `LLM cache get failed: ...`, `LLM cache set failed: ...`, or
`LLM cache delete failed: ...` and the
request goes to the LLM as if nothing were cached. `stats` counts `hits`,
`misses`, and `faults`, and `usage` is the wrapped client's, so cache hits cost
no tokens:

```python
print(llm.stats, llm.usage)
```
