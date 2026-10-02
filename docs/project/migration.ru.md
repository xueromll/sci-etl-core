# Руководство по миграции

Это руководство перечисляет, что меняется для существующего кода при переходе
на новый выпуск `sci-etl-core`, начиная с самого нового выпуска.
[CHANGELOG.md](changelog.md) перечисляет все изменения, включая дополнения, не
требующие никаких действий.

Закрепите диапазон минорных выпусков, например `sci-etl-core>=0.6.0,<0.7`, и
поднимайте верхнюю границу после того, как ваши тесты пройдут на следующем
минорном выпуске. Переходя с одного минорного выпуска на более поздний,
применяйте каждый промежуточный раздел, начиная с самого старого.

Чтобы впервые перенести существующий исследовательский конвейер на
библиотеку, следуйте разобранному примеру в разделе
[Перенос конвейера](https://xueromll.github.io/sci-etl-core/latest/guide/migrating-a-pipeline/).

- [Обновление до 0.6](#upgrading-to-06)
- [Обновление до 0.5.1](#upgrading-to-051)
- [Обновление до 0.5](#upgrading-to-05)
- [Обновление до 0.4](#upgrading-to-04)
- [Обновление до 0.3](#upgrading-to-03)

---

## Обновление до 0.6 {#upgrading-to-06}

0.6 меняет контракт данных: что возвращает экстрактор сущностей, как экспортёр
получает сущности, как библиотека ведёт журнал и что содержит базовая
установка. Это последний выпуск до 1.0, ломающий существующий контракт.
Требуйте новую минорную версию с используемыми вами extras:

```text
sci-etl-core[config,async,arxiv,llm,pdf,processors]>=0.6.0,<0.7
```

Файлы и базы данных состояния, кэши LLM, хранилища эмбеддингов и текстовые
индексы, записанные 0.5, открываются без изменений. Закэшированные ответы LLM
остаются действительными: запрос без схемы имеет тот же ключ кэша, что и в
0.5.1.

### Установите extras, которые импортируете {#install-the-extras-you-import}

Базовая установка теперь требует только Pydantic. PyYAML и python-dotenv
перенесены в extra `config`, Beautiful Soup и lxml — в `arxiv`, `html` и `xml`,
а pandas — в `processors`. `aiofiles` и `aiosqlite` больше не устанавливаются
ни одним extra. Импорт компонента, для которого не установлен нужный extra,
вызывает `ModuleNotFoundError` с именем пакета:

| Вы используете | Добавьте extra |
|----------------|----------------|
| `load_config`, `load_config_async`, `load_yaml` | `config` |
| `AsyncArxivExtractor` | `async`, `arxiv` |
| `AsyncPubMedExtractor` | `async`, `xml` |
| `JatsXmlParser`, `DocxParser` | `xml` |
| `HtmlTextParser` или `AsyncLLMEntityExtractor` для полного текста, начинающегося с разметки | `html` |
| что угодно в `sci_etl_core.processors`, кроме валидаторов | `processors` |

`full` по-прежнему устанавливает все встроенные компоненты, кроме локальных
эмбеддингов.

### Файлы `.env` читаются только по запросу {#env-files-are-read-only-when-asked}

`load_config` и `load_config_async` больше не ищут файл `.env` неявно.
Передайте файл или запросите поиск:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), load_env=True)
config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
```

Без одного из этих вариантов ключ API уже должен находиться в окружении.

### Экспортёры принимают запись и своё место назначения {#exporters-take-the-record-and-their-destination}

`AsyncExporter.export(data, destination)` заменён жизненным циклом. Конвейер
вызывает `open()` перед первым запросом выдачи, `write(record, entities)` для
каждой обработанной записи, включая запись без сущностей, `flush()` после
каждой страницы и `aclose()`, когда запуск заканчивается, как бы он ни
закончился. Экспортёр получает место назначения при создании, поэтому
аргумента `destination=` у конвейера больше нет:

```python
from sci_etl_core import AsyncCsvExporter, AsyncETLPipeline

pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager,
)
```

`AsyncCsvUpsertExporter` удалён. Его замена, `AsyncCsvExporter`, не
объединяет строки: он пишет по одной строке на сущность с `record_id`
статьи, из которой она получена, хранит прочие ключи в столбце `extra` и
записывает значения без изменений, так что значение никогда не обрезается, не
приводится и не теряется, а две статьи, сообщающие об одном объекте, дают две
строки. Объединяйте при постобработке, где выбор явный:

```python
import pandas as pd

from sci_etl_core.processors import DeduplicationStep, DefaultKeyNormalizer, NormalizationStep, ProcessorChain

raw = pd.read_csv("results.csv", dtype={"record_id": str, "name": str})
one_row_per_name = ProcessorChain(
    [NormalizationStep("name", DefaultKeyNormalizer()), DeduplicationStep("_norm_key")]
).process(raw)
```

Файл CSV записывается, когда запуск заканчивается; во время запуска страницы
идут в `results.csv.journal`, который следующий запуск воспроизводит, если
запуск аварийно завершился. Добавьте `*.journal` в `.gitignore` рядом со своим
выходным файлом. Заголовок нового файла — это `record_id`, ваши столбцы и
`extra`, поэтому начинайте новый файл, а не направляйте экспортёр на файл,
записанный `AsyncCsvUpsertExporter`; экспортёр отказывается работать с файлом
с другим заголовком. `AsyncJsonlExporter` вместо этого пишет по одной строке
JSON на запись.

Собственный экспортёр реализует `write`, а если использует буферизацию, то
устанавливает `durable_writes = False` и реализует `flush`:

```python
from sci_etl_core import AsyncExporter


class DatabaseExporter(AsyncExporter):
    def __init__(self, database):
        self.database = database

    async def write(self, record, entities):
        await self.database.replace_rows(record.record_id, list(entities))
```

`write` должен быть идемпотентным, поскольку сбой может повторить запись, а
запись без сущностей должна очищать то, что сохранила более ранняя запись.
Запись помечается как обработанная, только когда её сущности надёжно
сохранены: сразу после `write` или после `flush` страницы, когда
`durable_writes` равен `False`. Сбой `write` приводит к неудаче записи и
засчитывает одну попытку, сбой `flush` оставляет записанные на странице записи
незавершёнными без учёта попытки, а сбой `open` прерывает запуск до любого
запроса. [Семантика запуска](https://xueromll.github.io/sci-etl-core/latest/guide/run-semantics/)
нумерует это как R20–R23.

`AsyncSqlTableExporter` и `AsyncPlotly3DExporter` удалены; используйте
`SqlTableSink` и `Plotly3DSink` из `sci_etl_core.processors.sinks`, как
показано в разделе [Табличные приёмники](#table-sinks). `ScatterPlotConfig`
импортируется из `sci_etl_core.processors`.

### Экстракторы сущностей типизированы и учитывают запись {#entity-extractors-are-typed-and-record-aware}

`AsyncEntityExtractor` обобщён по типу сущности, а конвейер вызывает
`extract_record(record, text)`, реализация которого по умолчанию вызывает
`extract(text)`. Экстрактор, переопределяющий только `extract`, не требует
изменений. Обёртка вокруг другого экстрактора должна делегировать и
`extract_record`, чтобы продолжать работать вокруг экстрактора, которому нужна
запись, например `AsyncLLMClaimExtractor`:

```python
from sci_etl_core import AsyncEntityExtractor


class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(self, inner, validator):
        self.inner = inner
        self.validator = validator
        self.requires_record = inner.requires_record

    async def extract(self, text):
        return [entity for entity in await self.inner.extract(text) if self.validator.is_valid(entity)]

    async def extract_record(self, record, text):
        entities = await self.inner.extract_record(record, text)
        return [entity for entity in entities if self.validator.is_valid(entity)]
```

Такая обёртка обычно больше не нужна: `AsyncLLMEntityExtractor` принимает
`validator`, записывает в журнал каждое отклонение с причинами и может
сохранять отклонённые сущности в хранилище отклонений. Все аргументы после
`system_prompt` теперь только именованные.

Чтобы проверять сущности по модели Pydantic и получать экземпляры модели,
передайте `schema=`; см.
[Типизированные сущности и валидация](https://xueromll.github.io/sci-etl-core/latest/guide/typed-entities/).
Собственный `AsyncLLMClient`, оборачивающий другой, должен пробрасывать
`complete_structured` и принимать `schema=` в `invalidate`.

### Валидаторы объясняют причину {#validators-say-why}

`RecordValidator.validate(entity)` возвращает `ValidationResult` из
`Violation`. Валидатор, реализующий только `is_valid`, продолжает работать.
Валидатор, который уже вычисляет причину, например методом
`rejection_reason`, может вместо этого переопределить `validate`, и причина
попадёт в журнал и в хранилище отклонений:

```python
from sci_etl_core.processors import RecordValidator, ValidationResult, Violation


class RangeValidator(RecordValidator):
    def is_valid(self, record):
        return self.validate(record).ok

    def validate(self, record):
        radius = record.get("radius_kpc")
        if radius is not None and not 0.1 <= float(radius) <= 20.0:
            violation = Violation(code="out-of-range", field="radius_kpc", severity="error", message=f"radius {radius} kpc")
            return ValidationResult(violations=(violation,))
        return ValidationResult()
```

### Журналирование идёт через модуль `logging` {#logging-goes-through-the-logging-module}

Все аргументы `logger=` удалены: из `AsyncETLPipeline`, `ETLPipeline`, четырёх
экстракторов, `AsyncLLMEntityExtractor`, `CachingLLMClient`,
`AsyncCompositeIngestor`, `AsyncHybridSearcher` и `ShutdownSignal`.
`configure_logging` и `sci_etl_core.log_utils` удалены, как и
`AsyncETLPipeline.log`. Каждый модуль пишет журнал под собственным именем
ниже логгера `sci_etl_core`, поэтому настраивайте журналирование в
приложении:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler("output/pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
```

Сообщения сохраняют свои формулировки. `CachingLLMClient` принимал `logger`
четвёртым позиционным аргументом; вызов, передававший его позиционно, теперь
завершается `TypeError`.

### Удалённые имена {#removed-names}

Устаревания 0.5 удалены: блокирующие контракты `Extractor`, `StateManager`,
`Exporter`, `LLMClient`, `RelevanceFilter` и `EntityExtractor`; их адаптеры
`SyncExtractorAdapter`, `SyncRelevanceFilterAdapter`,
`SyncEntityExtractorAdapter`, `SyncExporterAdapter`, `SyncStateManagerAdapter`
и `SyncLLMClientAdapter`; `LegacyExtractorAdapter`; `AsyncExporter.export` и
аргумент `destination`; `AsyncCsvUpsertExporter`, `AsyncSqlTableExporter` и
`AsyncPlotly3DExporter`; а также `configure_logging`. Реализуйте асинхронные
контракты, выполняя блокирующую работу внутри них через `asyncio.to_thread`.
`ETLPipeline` остаётся и, как и раньше, запускает асинхронный конвейер из
блокирующего кода.

Начиная с 0.6 устаревшее имя продолжает работать как минимум два минорных
выпуска, прежде чем его удаляют.

## Обновление до 0.5.1 {#upgrading-to-051}

0.5.1 не ломает ни одного существующего вызова, но три исхода LLM, которые
раньше завершали запись, теперь приводят к её неудаче. Запись остаётся
непомеченной, её попытка засчитывается в `max_attempts`, и следующий запуск
повторяет её:

- **Пустой ответ.** `AsyncOpenAICompatibleClient.complete_json` выбрасывает
  `LLMError` вместо того, чтобы возвращать `{}`.
- **Ответ без списка сущностей.** `AsyncLLMEntityExtractor.extract`
  выбрасывает `LLMError`, когда ответ пуст или содержит несколько ключей и ни
  один из них не `result_key`, вместо того чтобы возвращать `[]`.
- **Сбой релевантности при `default_on_error=False`.**
  `AsyncLLMRelevanceFilter` и `AsyncEmbeddingRelevanceFilter` выбрасывают
  исключение вместо того, чтобы считать сбой ответом «нерелевантно», что
  навсегда помечало запись как обработанную.

Если ваша модель иногда отвечает пустым объектом или со списком сущностей под
другим ключом, такие записи теперь не удаются и помещаются в карантин после
`max_attempts` запусков. Называйте `result_key` в промпте. Собственный
`AsyncLLMClient` должен выбрасывать `LLMError` для ответа, который не может
прочитать, а не возвращать `{}`.

Записи, которые прежние выпуски пометили как обработанные таким образом,
остаются помеченными; к ним возвращается только запуск с новым состоянием.

Кэш LLM тоже меняется:

- **Каждый закэшированный ответ один раз даёт промах.** Ключ кэша теперь
  включает `base_url` конечной точки, температуру и формат ответа, поэтому
  первый запуск после обновления вызывает LLM для каждого запроса. Записи,
  сделанные прежними выпусками, больше никогда не читаются; удалите файл кэша
  или вызовите `clear()`, чтобы освободить место. Имя модели, в котором
  закодирована температура, например `"gpt-4o-mini@t0.2"`, больше не нужно.
- **Отвергнутые ответы удаляются.** `AsyncLLMEntityExtractor` и
  `AsyncLLMRelevanceFilter` вызывают `invalidate` у своего клиента, когда
  отвергают ответ, и `CachingLLMClient` удаляет его, поэтому повторная попытка
  доходит до модели. Собственный `AsyncLLMResponseCache` должен реализовывать
  `delete`. Собственный клиент, оборачивающий другой, должен пробрасывать ему
  `invalidate`.

## Обновление до 0.5 {#upgrading-to-05}

0.5 меняет то, как листают экстракторы, что сохраняет состояние и как
создаётся конвейер. Сущности и экспортёры меняются в 0.6. Требуйте новую
минорную версию и Python 3.11:

```text
sci-etl-core[async,llm,pdf]>=0.5.0,<0.6
```

Состояние, записанное 0.4, не требует преобразования. `AsyncSqliteStateManager`
обновляет свою базу данных на месте, а `AsyncFileStateManager` читает старый
файл метаданных и переписывает его в новом формате при следующем сохранении. В
любом случае сохранённое смещение становится курсором, поэтому следующий запуск
продолжает с того места, где остановился предыдущий.

### Экстракторы возвращают разобранные страницы {#extractors-return-parsed-pages}

`search` и `parse_listing` заменены одним `fetch_page`, который возвращает
`ListingPage`. Теперь конвейер сам пропускает обработанные записи, поэтому
экстрактор возвращает каждый элемент, который может прочитать. Источник,
листающий по смещению, реализует также `cursor_for_offset`, что делает его
`OffsetListing`.

До:

```python
class MyExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return await self._client.get_page(query, start_index, max_results)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        entries = parse(raw_listing)
        return [entry for entry in entries if entry.record_id not in seen_ids], len(entries)
```

После:

```python
class MyExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = int(cursor or 0)
        entries = parse(await self._client.get_page(query, offset, page_size))
        return ListingPage(
            records=tuple(entries),
            entries=len(entries),
            next_cursor=str(offset + len(entries)) if entries else None,
        )
```

Источник с непрозрачными токенами продолжения возвращает токен как
`next_cursor` и не реализует `cursor_for_offset`. Источник, останавливающийся
на собственном лимите результатов, возвращает `truncated=True` и
`next_cursor=None` на странице, которая до него доходит. Пока экстрактор не
перенесён, `LegacyExtractorAdapter(MyOldExtractor())` запускает его без
изменений в 0.5.x с `DeprecationWarning`; 0.6 удаляет этот адаптер.

Обёртка, пробрасывающая вызовы другому экстрактору, например журналирующая
прогресс, пробрасывает `fetch_page`, а также `cursor_for_offset`, когда
оборачивает `OffsetListing`:

```python
class LoggingExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return self._inner.cursor_for_offset(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self._log(f"Fetching listing page at cursor {cursor or 'start'}")
        return await self._inner.fetch_page(query, cursor, page_size)
```

`newest_first=True` и `start_index` больше 0 требуют `OffsetListing` и в
противном случае вызывают `ValueError` до любого запроса.
`AsyncArxivExtractor`, `AsyncPubMedExtractor` и
`AsyncSemanticScholarExtractor` являются `OffsetListing`.
`AsyncOpenAlexExtractor` теперь листает с помощью курсоров OpenAlex, поэтому
он заходит дальше первых 10 000 работ, но больше не поддерживает
`newest_first`; его первый запуск на 0.5 один раз перезапускает выдачу с первой
страницы, потому что смещение, сохранённое 0.4, не является курсором OpenAlex.

### Что сохраняет состояние {#what-the-state-saves}

`PipelineMetadata.cursor` заменяет `last_start_index`. Код, читающий
сохранённую позицию, читает курсор, который для `OffsetListing` является
десятичным смещением:

```python
metadata = await state.load_metadata()
saved_offset = int(metadata.cursor or 0)
```

События прогресса получают `cursor`. `RunStarted.start_index`,
`PageFetched.offset` и `PageFinished.offset` по-прежнему содержат смещение в
выдаче для `OffsetListing` и равны `None` для любого другого экстрактора.

### Выдачи с лимитом начинаются заново {#capped-listings-start-over}

PubMed останавливается на 9 999 результатах, Semantic Scholar — на 1 000. В 0.4
запуск, доходивший до лимита, сохранял лимит как своё смещение, и каждый
последующий запуск сразу же заканчивался там. В 0.5 страница, достигающая
лимита, завершает запуск со статусом `"completed"`,
`RunMetrics.listing_truncated` сообщает об этом, а сохранённый курсор
сбрасывается, поэтому следующий запуск снова листает доступные результаты:
обработанные записи пропускаются по идентификатору, поэтому повторное
сканирование стоит запросов выдачи, а не вызовов LLM. Чтобы его избежать,
сузьте запрос, например по дате.

### Записи, которые продолжают проваливаться, помещаются в карантин {#records-that-keep-failing-are-quarantined}

Запись, которая не удалась в 3 запусках, каждый раз на странице, где была
обработана другая запись, начиная со следующего запуска пропускается как
находящаяся в карантине и учитывается в `RunMetrics.quarantined`. Неудачи на
странице, где ничего не было обработано, например во время сбоя сервиса или с
отвергнутым ключом API, никогда не учитываются. Чтобы сохранить поведение 0.4,
повторяя каждую неудавшуюся запись бесконечно:

```python
await pipeline.run(query, page_size=100, total_limit=500, max_attempts=None)
```

Сторонний менеджер состояния продолжает работать без изменений: у новых
`record_failure` и `failure_counts` есть реализации по умолчанию, которые
ничего не отслеживают, поэтому он никогда не помещает записи в карантин.

### Именованные аргументы {#keyword-arguments}

`AsyncETLPipeline` и `ETLPipeline` принимают пять компонентов позиционно или по
имени, а всё остальное — только по имени. `run` принимает `query`, а затем только
именованные аргументы, и `max_records=` больше нет:

```python
pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    exporter,
    state_manager,
    destination="results.csv",
    max_concurrency=4,
)
await pipeline.run("all:galaxy", page_size=50, total_limit=200)
```

`RawRecord`, `PipelineMetadata`, `TokenUsage`, `RunMetrics` и события
принимают только именованные аргументы, поэтому
`RawRecord("id", "title", "abstract")` становится
`RawRecord(record_id="id", title="title", abstract="abstract")`.

### Строгие разделы конфигурации {#strict-config-sections}

Ключ, который встроенный раздел не объявляет, теперь не проходит валидацию и
называется в `ConfigurationError`, поэтому опечатка вроде `search.bm25.titel`
или прежний ключ `pipeline.max_records` больше не проходят молча.
Переименуйте `pipeline.max_records` в `total_limit`, а `pipeline.max_workers` —
в `max_concurrency`. Приложение, которому пока нужно принимать неизвестные
ключи, отключает строгость в своём классе конфигурации, и о каждом отброшенном
ключе сообщается через `UserWarning`:

```python
class AppConfig(BaseAppConfig):
    strict_sections = False
```

Разделы верхнего уровня, которые определяет приложение, сохраняются, как и
раньше.

### Табличные приёмники {#table-sinks}

`AsyncSqlTableExporter` и `AsyncPlotly3DExporter` принимали `DataFrame` и не
могли работать в конвейере. Их замена — блокирующие приёмники для результатов
постобработки:

```python
from sci_etl_core.processors.sinks import Plotly3DSink, ScatterPlotConfig, SqlTableSink

catalogue = chain.process(raw_table)
SqlTableSink("sqlite:///catalogue.db", "galaxies", if_exists="replace").write(catalogue)
Plotly3DSink(ScatterPlotConfig("x", "y", "z", color_column="size"), "catalogue.html").write(catalogue)
```

### Устаревания без замены до 0.6 {#deprecations-with-no-replacement-before-06}

Эти имена продолжают работать в 0.5.x и выдают `PendingDeprecationWarning`, а не
`DeprecationWarning`, потому что их замены выходят в 0.6 и менять пока нечего:
аргумент `destination`, `AsyncExporter.export` и `AsyncCsvUpsertExporter`
(заменены жизненным циклом экспортёра и `AsyncCsvExporter`), а также каждый
аргумент `logger=` и `configure_logging` (заменены стандартным модулем
`logging`). Поэтому набор тестов, запущенный с
`-W error::DeprecationWarning`, продолжает проходить, пока их использует.

Блокирующие контракты и их `Sync*Adapter`, `LegacyExtractorAdapter` и два
табличных экспортёра выдают `DeprecationWarning`, потому что их замены уже
есть в 0.5; переходите на асинхронные контракты, которые уже реализует каждый
компонент, на `fetch_page` и на табличные приёмники.

`build_retrying_session` удалён, а extra `full` больше не устанавливает
`requests`.

## Обновление до 0.4 {#upgrading-to-04}

```text
sci-etl-core[async]>=0.4.0,<0.5
```

0.4 добавляет новые источники, парсеры, кэширование ответов LLM, корректное
завершение, события прогресса, ограничители частоты и функции поиска. На
существующий код влияют следующие изменения:

- **Переименованные настройки конвейера.** `pipeline.max_records` теперь
  называется `total_limit`, а `pipeline.max_workers` — `max_concurrency`.
  Старые ключи YAML и свойства `PipelineConfig.max_records` и `max_workers`
  продолжают работать до 0.5 с `DeprecationWarning`, а `run(max_records=)`
  устарел так же. Переименуйте оба ключа в своём файле конфигурации.
- **Больше настроек конвейера.** В `PipelineConfig` теперь есть `page_size`,
  `search_delay` и `newest_first`. Подкласс, который добавлял только эти поля,
  можно удалить.
- **Валидация без обёртки.** `AsyncLLMEntityExtractor` принимает
  `validator=`, `logger=` и `label_field=` и записывает в журнал каждую
  отбрасываемую сущность как `Entity rejected by validation: <label>`.
  Экстрактор, который оборачивал его только ради применения
  `RecordValidator`, можно удалить.
- **Компоненты из конфигурации.** `AsyncArxivExtractor.from_config`,
  `AsyncOpenAICompatibleClient.from_config` и `AsyncETLPipeline.from_config`
  читают разделы `http`, `llm` и `pipeline`, `config.http.build_client()`
  заменяет `build_async_client`, а `config.pipeline.run_arguments()`
  возвращает аргументы для `run()`, так что настройки больше не нужно вручную
  копировать в конструкторы.
- **Возобновление «сначала новые».** `run(newest_first=True)` подхватывает
  новые поступления arXiv без полного повторного сканирования, которого стоит
  `start_index=0`, и сохраняет начало выдачи в файле метаданных рядом с
  `last_start_index`. `start_index` с ним сочетать нельзя.
- **Графики.** `ScatterPlotConfig` принимает `hover_data_columns`,
  `hover_template`, `color_continuous_scale` и `color_range`, которые
  покрывают собственные всплывающие подсказки и фиксированные диапазоны
  цветов, раньше требовавшие построения фигуры вручную.
- **Зажатие и раскладка таблицы.** `ValueClipStep` зажимает столбцы при
  постобработке, а `TableLayoutStep` сортирует строки и упорядочивает столбцы
  вместо процессоров конкретного проекта, делавших то или другое.
- **Поиск по уже имеющейся памяти.** Проект, хранивший фрагменты в
  `AsyncSqliteEmbeddingStore`, может построить из них текстовый индекс с
  помощью `backfill_text_index`, а не загружать каждую статью заново.
- **Сниппеты для семантических результатов.** `FusedHit`, найденный только
  семантической ветвью, теперь несёт сниппет своего лучшего фрагмента, тогда
  как раньше у него был пустой `snippet`. Интерфейсу, который показывал
  аннотацию всякий раз, когда `snippet` был пуст, следует вместо этого
  проверять `lexical_rank is None`.
- **Устаревший помощник для `requests`.** `build_retrying_session` выдаёт
  предупреждение и будет удалён в 0.5 вместе с `requests` в extra `full`.

## Обновление до 0.3 {#upgrading-to-03}

```text
sci-etl-core[async]>=0.3.0,<0.4
```

0.3 добавляет локальный поиск и графы связанных статей. На существующий код
влияют следующие изменения:

- **Записи arXiv несут метаданные.** `RawRecord.metadata` теперь содержит
  `categories`, `authors`, `published` и `year`, а не остаётся пустым. Ваш
  собственный код, читающий записи, включая тесты, сравнивающие
  `metadata == {}`, видит новые ключи. Метаданные, сохраняемые вместе с
  фрагментами эмбеддингов, не изменились.
- **`memory_ingestor` принимает любой `MemoryIngestor`.** `AsyncChunkIngestor`
  работает точно так же, как раньше. Аннотацию типа в вашем коде, называющую
  `AsyncChunkIngestor` для этого аргумента, можно расширить до
  `MemoryIngestor`.
- **Поиск включается по желанию.** В конвейере, не передающем текстовый
  индекс, ничего не меняется. Чтобы добавить его, передайте
  `AsyncSearchIndexer` или `AsyncCompositeIngestor` с загрузчиком фрагментов на
  первом месте, как показано в разделе
  [Локальный поиск и обзор](https://xueromll.github.io/sci-etl-core/latest/guide/search/).
  Его `AsyncSqliteFts5Store` помещается в `closeables`, как и любое другое
  хранилище SQLite.
- **Состояние в SQLite безопаснее при отмене.** `AsyncSqliteStateManager`
  больше не позволяет рабочему потоку отменённой операции пересекаться со
  следующей операцией. `AsyncFileStateManager` не изменился.

Есть вопросы или шероховатость при обновлении? Откройте
[issue](https://github.com/xueromll/sci-etl-core/blob/master/.github/ISSUE_TEMPLATE/bug_report.md) —
мы будем рады помочь.
