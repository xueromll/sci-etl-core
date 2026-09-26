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
llm = CachingLLMClient(AsyncOpenAICompatibleClient.from_config(config.llm), cache)

relevance_filter = AsyncLLMRelevanceFilter(llm, relevance_prompt)
entity_extractor = AsyncLLMEntityExtractor(llm, extraction_prompt)
```

List the SQLite cache in the pipeline's `closeables` so its connection is
closed at the end of the run.

## How requests are matched

A request is keyed on the model name, the endpoint's `base_url`, the
temperature, the response format, the JSON Schema of a typed request, the
client's `variant`, and both prompts, hashed with SHA-256; the timeout isn't
part of the key. A changed system prompt, a changed paper text, a different
model, a different provider, a different temperature, a different response
format, or a changed entity schema is a miss. The schema is serialized with
sorted keys, so an equal schema written in another order still hits. A request
without a schema and with an empty `variant` has the same key it had in
0.5.1.

`CachingLLMClient(..., variant="sample-2")` keeps its answers apart from those
of a client with another variant over the same cache, for example to ask a
question twice on purpose.

`CachingLLMClient` reads `base_url`, `temperature`, and `response_format` from
the client it wraps. `AsyncOpenAICompatibleClient` exposes all three. Every
client has a `response_format`, `{"type": "json_object"}` unless a subclass
overrides it; a custom client without `base_url` or `temperature` is keyed
without them.

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
`LLM cache delete failed: ...`, at `WARNING` on the
`sci_etl_core.llm.cache_async` logger, and the request goes to the LLM as if
nothing were cached. `stats` counts `hits`,
`misses`, and `faults`, and `usage` is the wrapped client's, so cache hits cost
no tokens:

```python
print(llm.stats, llm.usage)
```
