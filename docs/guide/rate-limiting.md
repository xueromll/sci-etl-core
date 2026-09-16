# Rate limiting

`AsyncETLPipeline(max_concurrency=...)` bounds how many records are processed
at once. For finer control, `sci_etl_core.rate_limiter` provides standalone
async context managers:

- `SemaphoreRateLimiter` — concurrency cap
- `AioLimiterRateLimiter` — token bucket; needs the `async` extra
- `NullRateLimiter` — no limit

`build_rate_limiter(max_concurrency, max_rate, time_period)` returns a token
bucket when `max_rate` is set and a semaphore otherwise. Its parameters match
the `full_text` [config section](../getting-started/configuration.md).
Components don't take a limiter argument, so apply one by wrapping a
component:

```python
from sci_etl_core.extractors import AsyncExtractor
from sci_etl_core.rate_limiter import AsyncRateLimiter, build_rate_limiter


class RateLimitedExtractor(AsyncExtractor):
    """Route an extractor's network calls through one shared limiter."""

    def __init__(self, inner: AsyncExtractor, limiter: AsyncRateLimiter) -> None:
        self._inner = inner
        self._limiter = limiter

    async def search(self, query, max_results, start_index):
        async with self._limiter:
            return await self._inner.search(query, max_results, start_index)

    def parse_listing(self, raw_listing, seen_ids):
        return self._inner.parse_listing(raw_listing, seen_ids)

    async def fetch_full_text(self, record):
        async with self._limiter:
            return await self._inner.fetch_full_text(record)
```

Wrap the extractor with a limiter built from the config:

```python
extractor = RateLimitedExtractor(
    AsyncArxivExtractor(...),
    build_rate_limiter(**config.full_text.model_dump()),
)
```
