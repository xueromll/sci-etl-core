# Retries

`AsyncArxivExtractor`, `AsyncOpenAICompatibleClient`, and `AsyncOpenAIEmbedder`
retry throttling (`429`), server errors, and transport faults, making at most
`max_retries` attempts per request (default 3):

- **Backoff.** Between attempts they wait `backoff_factor ** attempt` seconds:
  1 s, then 2 s with the default factor of 2.
- **`Retry-After`.** When a response says how long to wait, in `Retry-After`
  or the `retry-after-ms` header OpenAI-compatible APIs send, they wait that
  long instead whenever it is longer than the backoff, up to `max_retry_after`
  seconds (default 60).
- **One retry layer.** The OpenAI SDK's own retries are turned off, so
  `max_retries` is the total number of attempts.
- **Visibility.** The arXiv extractor logs each retry and its wait through
  `logger`.

The client from `build_async_client` also retries failed connections at the
transport level (`total_retries`, default 5) before the extractor counts one
failed attempt.
