# Consumo de tokens

`AsyncOpenAICompatibleClient.usage` y `AsyncOpenAIEmbedder.usage` devuelven
una instantánea `TokenUsage` contabilizada sobre todas las respuestas que ha
recibido el cliente, incluidas las respuestas cuyo cuerpo se rechazó después:

```python
async with pipeline:
    await pipeline.run(query="all:galaxy", total_limit=50)
usage = llm.usage
print(f"{usage.requests} requests, {usage.prompt_tokens} prompt and {usage.completion_tokens} completion tokens")
```

`TokenUsage` tiene `requests`, `prompt_tokens`, `completion_tokens` y
`total_tokens`. Una respuesta sin datos de consumo cuenta como una solicitud
con cero tokens. Otras implementaciones de `AsyncLLMClient` y `AsyncEmbedder`
devuelven `None` a menos que sobrescriban la propiedad `usage`.
