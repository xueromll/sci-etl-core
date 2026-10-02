# Ограничение частоты запросов

`AsyncETLPipeline(max_concurrency=...)` ограничивает число записей,
обрабатываемых одновременно. Для более тонкого контроля
`sci_etl_core.rate_limiter` предоставляет асинхронные ограничители:

- `SemaphoreRateLimiter` — ограничение параллелизма
- `AioLimiterRateLimiter` — «ведро токенов»; нужен extra `async`
- `NullRateLimiter` — без ограничений

`build_rate_limiter(max_concurrency, max_rate, time_period)` возвращает
«ведро токенов», если задан `max_rate`, и семафор в противном случае. Его
параметры совпадают с [разделом конфигурации](../getting-started/configuration.md)
`full_text`.

## Передача ограничителя компоненту {#giving-a-limiter-to-a-component}

Каждый встроенный экстрактор (`AsyncArxivExtractor`, `AsyncPubMedExtractor`,
`AsyncSemanticScholarExtractor` и `AsyncOpenAlexExtractor`),
`AsyncOpenAICompatibleClient` и `AsyncOpenAIEmbedder` принимают
`rate_limiter`. Каждый HTTP-запрос, включая повторные, сначала ждёт свободного
слота и возвращает его, когда приходит ответ, поэтому ни один слот не занят,
пока компонент ждёт повторной попытки:

```python
from sci_etl_core import AsyncArxivExtractor
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncArxivExtractor(
    client=client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    rate_limiter=build_rate_limiter(max_rate=1, time_period=3.0),
)
```

## Ограничения по хостам {#limits-per-host}

`HostRateLimiter` выбирает ограничитель по хосту, к которому идёт запрос. Хост
охватывает и свои поддомены, если у поддомена нет собственного ограничителя, а
хосты без совпадения используют `default`, что означает отсутствие ограничения,
если его не указать. Экстрактор arXiv обращается к двум хостам —
`export.arxiv.org` для выдачи и `arxiv.org` для полного текста, — поэтому
каждый может получить собственный бюджет:

```python
from sci_etl_core.rate_limiter import HostRateLimiter, SemaphoreRateLimiter, build_rate_limiter

arxiv_limits = HostRateLimiter(
    {
        "export.arxiv.org": build_rate_limiter(max_rate=1, time_period=3.0),
        "arxiv.org": SemaphoreRateLimiter(max_concurrency=4),
    }
)
```

## Общее ограничение для нескольких компонентов {#sharing-a-limit-between-components}

Передайте один и тот же ограничитель нескольким компонентам, чтобы они делили
один бюджет. Чат-клиент и эмбеддер, обращающиеся к одному провайдеру,
расходуют одну и ту же квоту:

```python
from sci_etl_core import AsyncOpenAICompatibleClient, AsyncOpenAIEmbedder
from sci_etl_core.rate_limiter import build_rate_limiter

provider_limit = build_rate_limiter(max_rate=50, time_period=60.0)
llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    rate_limiter=provider_limit,
)
embedder = AsyncOpenAIEmbedder(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model="text-embedding-3-small",
    rate_limiter=provider_limit,
)
```

`HostRateLimiter` можно разделять так же, например один экземпляр, хосты
которого охватывают все сервисы, вызываемые запуском. OpenAI-совместимые
клиенты сопоставляют его со своим `base_url`.
