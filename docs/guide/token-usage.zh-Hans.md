# Token 用量

`AsyncOpenAICompatibleClient.usage` 和 `AsyncOpenAIEmbedder.usage` 返回一个
`TokenUsage` 快照，统计范围是该客户端收到的所有响应，包括响应体随后被拒绝的响应：

```python
async with pipeline:
    await pipeline.run(query="all:galaxy", total_limit=50)
usage = llm.usage
print(f"{usage.requests} requests, {usage.prompt_tokens} prompt and {usage.completion_tokens} completion tokens")
```

`TokenUsage` 包含 `requests`、`prompt_tokens`、`completion_tokens` 和
`total_tokens`。没有用量数据的响应按一次请求、零个 token 计数。其他
`AsyncLLMClient` 和 `AsyncEmbedder` 实现除非重写 `usage` 属性，否则返回 `None`。
