# Token usage

`AsyncOpenAICompatibleClient.usage` and `AsyncOpenAIEmbedder.usage` return a
`TokenUsage` snapshot counted across every response the client has received,
including responses whose body was then rejected:

```python
async with pipeline:
    await pipeline.run(query="all:galaxy", total_limit=50)
usage = llm.usage
print(f"{usage.requests} requests, {usage.prompt_tokens} prompt and {usage.completion_tokens} completion tokens")
```

`TokenUsage` has `requests`, `prompt_tokens`, `completion_tokens`, and
`total_tokens`. A response without usage data counts as a request with zero
tokens. Other `AsyncLLMClient` and `AsyncEmbedder` implementations return
`None` unless they override the `usage` property.
