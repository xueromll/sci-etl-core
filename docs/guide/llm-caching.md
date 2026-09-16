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

A request is keyed on the model name and both prompts, hashed with SHA-256; the
timeout isn't part of the key. A changed system prompt, a changed paper text,
or a different model is a miss.

Anything else that changes the answer, such as the temperature, isn't part of
the key. Give the cache a model name that includes it:

```python
llm = CachingLLMClient(client, cache, model="gpt-4o-mini@t0.2")
```

Only successful responses are cached, so a request that failed is sent again
next time.

## Backends

- **`InMemoryLLMResponseCache(max_entries=None)`** lives as long as the process.
  With `max_entries`, the least recently used response is evicted once it's
  full.
- **`AsyncSqliteLLMResponseCache(path)`** keeps responses in a SQLite file
  between runs. `clear()` empties it and `count()` reports its size.

A custom backend, such as Redis, subclasses `AsyncLLMResponseCache` and
implements `get`, `set`, and `clear`.

## When the cache fails

The cache never fails a completion. If reading or writing it raises, the error
is logged as `LLM cache get failed: ...` or `LLM cache set failed: ...` and the
request goes to the LLM as if nothing were cached. `stats` counts `hits`,
`misses`, and `faults`, and `usage` is the wrapped client's, so cache hits cost
no tokens:

```python
print(llm.stats, llm.usage)
```
