# Расход токенов

`AsyncOpenAICompatibleClient.usage` и `AsyncOpenAIEmbedder.usage` возвращают
снимок `TokenUsage`, подсчитанный по всем ответам, которые получил клиент,
включая ответы, тело которых затем было отклонено:

```python
async with pipeline:
    await pipeline.run(query="all:galaxy", total_limit=50)
usage = llm.usage
print(f"{usage.requests} requests, {usage.prompt_tokens} prompt and {usage.completion_tokens} completion tokens")
```

У `TokenUsage` есть поля `requests`, `prompt_tokens`, `completion_tokens` и
`total_tokens`. Ответ без данных о расходе считается запросом с нулём
токенов. Другие реализации `AsyncLLMClient` и `AsyncEmbedder` возвращают
`None`, если не переопределяют свойство `usage`.
