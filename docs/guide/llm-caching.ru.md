# Кэширование ответов LLM

Повторный запуск пайплайна после сбоя, правки промпта в другом месте или
изменения кода экспорта снова задаёт LLM те же вопросы. `CachingLLMClient`
отвечает на повторяющиеся запросы из кэша, поэтому они не стоят токенов и
возвращаются мгновенно:

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

Укажите кэш SQLite в `closeables` пайплайна, чтобы его соединение закрывалось
в конце запуска.

## Как сопоставляются запросы {#how-requests-are-matched}

Ключ запроса строится по имени модели, `base_url` конечной точки, температуре,
формату ответа, JSON Schema типизированного запроса, `variant` клиента и обоим
промптам и хэшируется SHA-256; тайм-аут в ключ не входит. Изменённый
системный промпт, изменённый текст статьи, другая модель, другой провайдер,
другая температура, другой формат ответа или изменённая схема сущности дают
промах. Схема сериализуется с отсортированными ключами, поэтому равная схема,
записанная в другом порядке, всё равно даёт попадание. Запрос без схемы и с
пустым `variant` имеет тот же ключ, что и в 0.5.1.

`CachingLLMClient(..., variant="sample-2")` хранит свои ответы отдельно от
ответов клиента с другим вариантом в том же кэше — например, чтобы намеренно
задать вопрос дважды.

`CachingLLMClient` читает `base_url`, `temperature` и `response_format` у
клиента, который оборачивает. `AsyncOpenAICompatibleClient` предоставляет все
три. У каждого клиента есть `response_format`, равный
`{"type": "json_object"}`, если подкласс его не переопределяет; собственный
клиент без `base_url` или `temperature` получает ключ без них.

## Что кэшируется {#what-is-cached}

Неудавшийся запрос никогда не кэшируется, поэтому в следующий раз он
отправляется снова. Ответ, который отвергает библиотека, тоже не сохраняется:

- `AsyncLLMEntityExtractor` отвергает ответ, в котором нет списка сущностей,
  или чей список сущностей не является списком объектов.
- `AsyncLLMRelevanceFilter` отвергает ответ без однозначного вердикта.

Оба вызывают у клиента `invalidate`, и `CachingLLMClient` удаляет
закэшированный ответ, поэтому повторная попытка при следующем запуске
доходит до модели, а не воспроизводит тот же ответ.

## Бэкенды {#backends}

- **`InMemoryLLMResponseCache(max_entries=None)`** живёт столько же, сколько
  процесс. С `max_entries` при заполнении вытесняется ответ, который
  использовался давнее всех.
- **`AsyncSqliteLLMResponseCache(path)`** хранит ответы в файле SQLite между
  запусками. `clear()` очищает его, а `count()` сообщает его размер.

Собственный бэкенд, например Redis, наследует `AsyncLLMResponseCache` и
реализует `get`, `set`, `delete` и `clear`. Бэкенд без `delete` всё равно
работает, но каждый отвергнутый ответ остаётся в кэше и записывается в журнал
как сбой кэша.

## Когда кэш отказывает {#when-the-cache-fails}

Кэш никогда не приводит к неудаче запроса к модели. Если чтение или запись
кэша выбрасывает исключение, ошибка записывается в журнал как
`LLM cache get failed: ...`, `LLM cache set failed: ...` или
`LLM cache delete failed: ...` с уровнем `WARNING` в логгер
`sci_etl_core.llm.cache_async`, а запрос уходит к LLM, как если бы в кэше
ничего не было. `stats` считает `hits`, `misses` и `faults`, а `usage` — это
расход обёрнутого клиента, поэтому попадания в кэш не стоят токенов:

```python
print(llm.stats, llm.usage)
```
