# Конфигурация

Настройки загружаются из файла YAML и, при желании, из файла `.env` в модели
Pydantic. Для загрузки нужен extra `config`:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
print(config.llm.model, config.pipeline.total_limit)
```

```yaml title="config.yaml"
llm:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  timeout: 120
http:
  user_agent: "my-project/1.0 (mailto:you@example.org)"
  max_retries: 3
  timeout: 25
full_text:
  max_concurrency: 4
pipeline:
  search_query: "all:galaxy"
  total_limit: 100
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_concurrency: 6
  newest_first: true
search:
  bm25: {title: 10, abstract: 4, body: 1}
  fusion: {k: 60}
  hybrid: {candidate_pool: 100, chunk_pool_factor: 5}
  graph: {depth: 2, fanout: 8, min_weight: 0.35}
```

| Раздел | Модель | Поля (значения по умолчанию) | Что строит |
|--------|--------|------------------------------|------------|
| `llm` | `LLMConfig` | `api_key`, `base_url` (`https://api.openai.com/v1`), `model` (`gpt-4o-mini`), `timeout` (120), `structured_output` (false) | `AsyncOpenAICompatibleClient.from_config` |
| `http` | `HttpConfig` | `user_agent` (`sci-etl-core/<installed version>`), `max_retries` (3), `backoff_factor` (2.0), `timeout` (25) | `build_client()`, `AsyncArxivExtractor.from_config` |
| `full_text` | `RateLimitConfig` | `max_concurrency` (4), `max_rate` (не задан), `time_period` (1.0) | `build_limiter()`, `AsyncArxivExtractor.from_config` |
| `pipeline` | `PipelineConfig` | `search_query` (`""`), `total_limit` (100), `page_size` (100), `search_delay` (3.0), `sleep_between` (5.0), `max_concurrency` (6), `newest_first` (false) | `AsyncETLPipeline.from_config`, `run_arguments()`, `AsyncArxivExtractor.from_config` |
| `search` | `SearchConfig` | `bm25`, `fusion`, `hybrid`, `graph` со значениями по умолчанию тех dataclass, которые они строят | `bm25.to_weights()`, `fusion.to_params()`, `hybrid.to_params()`, `graph.to_params()` |

## Создание компонентов из конфигурации {#building-components-from-the-config}

Каждый раздел строит компоненты, которые настраивает, или передаётся им.
Значения, которые вы передаёте сами, имеют приоритет над конфигурацией:

```python
from sci_etl_core import AsyncArxivExtractor, AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

extractor = AsyncArxivExtractor.from_config(
    config.http,
    config.pipeline,
    client=config.http.build_client(),
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    full_text=config.full_text,
)
llm = AsyncOpenAICompatibleClient.from_config(config.llm)
pipeline = AsyncETLPipeline.from_config(
    config.pipeline,
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
)
await pipeline.run(**config.pipeline.run_arguments())
```

`AsyncArxivExtractor.from_config` берёт `max_retries` и `backoff_factor` из
`http`, `search_delay` из `pipeline`, а свой `rate_limiter` — из `full_text`.
Если опустить `full_text`, у экстрактора не будет ограничителя частоты, и
пайплайн с `max_concurrency`, равным 6, будет загружать с arxiv.org шесть
статей одновременно. `AsyncOpenAICompatibleClient` берёт `api_key`
(загруженный `SecretStr` как есть), `base_url`, `model`, `structured_output`
и `timeout` в качестве `default_timeout`. Устанавливайте
`structured_output: true` только для конечной точки, которая принимает формат
ответа `json_schema`, как у OpenAI; у DeepSeek такого нет. Оба принимают любой
другой аргумент конструктора, например `rate_limiter`, как именованный.
У экстракторов PubMed, Semantic Scholar и OpenAlex нет `from_config`;
передавайте `config.http.max_retries` и `config.http.backoff_factor` в их
конструкторы сами. Пайплайн берёт `max_concurrency`, а `run_arguments()`
возвращает для `run()` значения `query`, `page_size`, `total_limit`,
`sleep_between` и `newest_first`; добавляйте `max_attempts` или `start_index`
сами, когда они нужны. `ETLPipeline.from_config` работает так же.

Раздел search строит dataclass с параметрами для
[локального поиска](../guide/search/index.md):

```python
from sci_etl_core.search import AsyncHybridSearcher, AsyncSqliteFts5Store

store = AsyncSqliteFts5Store("search.db", weights=config.search.bm25.to_weights())
searcher = AsyncHybridSearcher(
    store,
    finder,
    fusion=config.search.fusion.to_params(),
    params=config.search.hybrid.to_params(),
)
```

## Строгие разделы {#strict-sections}

Каждый раздел, определённый библиотекой, отвергает ключ, который он не
объявляет, поэтому опечатка приводит к явной ошибке, а не игнорируется.
`ConfigurationError` называет ключ:

```text
Invalid configuration in config.yaml:
  search.bm25.titel: Extra inputs are not permitted
```

Ключи `pipeline.max_records` и `pipeline.max_workers`, переименованные в 0.4,
начиная с 0.5 отвергаются так же; используйте `total_limit` и
`max_concurrency`. Приложение, которому всё ещё нужно загружать файл с
неизвестными ключами в разделах библиотеки, устанавливает
`strict_sections = False` в своём классе конфигурации. Тогда каждый
неизвестный ключ отбрасывается с `UserWarning`, в котором он назван:

```python
from sci_etl_core import BaseAppConfig


class MyConfig(BaseAppConfig):
    strict_sections = False
```

Разделы верхнего уровня, которые добавляет ваше приложение, сохраняются в
любом случае, а тип раздела, который вы определяете сами, проверяется так, как
указывает его собственный `model_config`.

## Подробности {#details}

- **Ключ API.** Ключ берётся из переменной окружения `LLM_API_KEY` (другую
  можно выбрать через `api_key_env_var=`). Файл `.env` читается в окружение
  только по вашему запросу: передайте его путь как `env_path` или передайте
  `load_env=True`, чтобы использовать первый `.env`, найденный от текущего
  рабочего каталога вверх. Без одного из этих вариантов `load_config` никогда
  не читает файл `.env`, поэтому импорт и настройка библиотеки не меняют ни
  одной переменной окружения. Ключ хранится как Pydantic `SecretStr`, поэтому
  он не появляется в repr и в журналах. Переменные, уже заданные в окружении,
  имеют приоритет над `.env`; для начала скопируйте `.env.example`.
- **Окружение важнее YAML.** Когда переменная задана, она перекрывает любой
  `llm.api_key` в файле YAML, который используется только как запасной
  вариант. И всё же не храните ключи в файлах конфигурации.
- **Настройки конкретного проекта.** `BaseAppConfig` принимает
  дополнительные ключи верхнего уровня, или его можно унаследовать. Ключи
  внутри собственных разделов библиотеки должны быть объявлены этими
  разделами; см. [Строгие разделы](#strict-sections).
- **Асинхронная загрузка.** `load_config_async` принимает те же аргументы.
- **Ошибки.** Отсутствующий или неразбираемый файл YAML, файл, верхний
  уровень которого не является отображением, и неудачная валидация вызывают
  `ConfigurationError`. Валидация проверяет и диапазоны: счётчики, такие как
  `max_concurrency`, `page_size` и `max_retries`, должны быть не меньше 1,
  тайм-ауты и `time_period` — положительными, задержки и `total_limit` — не
  отрицательными, веса BM25 — конечными и неотрицательными, а
  `graph.min_weight` — конечным. `fusion.weights` проверяется только тогда,
  когда `fusion.to_params()` строит параметры, и для отрицательного или
  бесконечного веса вызывается `ValueError`. Сообщение валидации перечисляет
  каждый ошибочный ключ и причину на отдельной строке, но никогда не значение,
  поэтому ключ API не может попасть через него в журнал.
  `validate_config(config_cls, raw, source)` применяет те же проверки к
  настройкам, загруженным иным способом.
