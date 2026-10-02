# Журнал изменений

Здесь фиксируются все заметные изменения sci-etl-core. Формат следует
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), а версии следуют
[семантическому версионированию](https://semver.org/). До 1.0 минорный
выпуск может менять поведение; каждое такое изменение перечислено в разделе
**Изменено**.


## [0.6.0] - 2026-09-27 {#060-2026-09-27}

Этот выпуск меняет контракт данных: экстракторы сущностей могут возвращать
типизированные сущности, экспортёры получают каждую запись вместе с её
сущностями, библиотека пишет журнал через стандартный модуль `logging`, а
базовой установке нужен только Pydantic. Он добавляет утверждения с
доказательствами и происхождением. См. раздел «Обновление до 0.6» в
MIGRATION.md.

### Добавлено {#added}

- **Жизненный цикл экспортёра.** У `AsyncExporter` есть `open()`,
  `write(record, entities)`, `flush()` и `aclose()`, а `durable_writes`
  указывает, что делает сущности надёжно сохранёнными — `write` или `flush`.
  Конвейер помечает запись как обработанную, только когда её сущности надёжно
  сохранены, поэтому сбой может повторить запись, но никогда её не потеряет.
- `AsyncCsvExporter`, который пишет по одной строке на сущность с `record_id`
  её статьи, хранит все прочие ключи в столбце `extra` и никогда не объединяет,
  не обрезает и не приводит значения. Он формирует файл один раз за запуск из
  журнала, в который только дописываются данные, поэтому время экспорта растёт
  линейно с числом записей. Ячейки, которые электронная таблица выполнила бы как
  формулу, получают ведущий апостроф; простые числа, такие как `-5.361`,
  записываются без изменений.
- `AsyncJsonlExporter`, который дописывает по одной строке JSON на запись, и
  `read_jsonl_export`, который читает обратно последнюю строку каждой записи.
- **Типизированные сущности.** `AsyncLLMEntityExtractor(schema=Model)`
  проверяет каждую сущность по модели Pydantic и возвращает экземпляры модели.
  Он запрашивает структурированный вывод по JSON Schema через новый
  `AsyncLLMClient.complete_structured`, который
  `AsyncOpenAICompatibleClient(structured_output=True)` и
  `LLMConfig.structured_output` включают для конечных точек, которые его
  поддерживают. `entity_list_schema` строит запрашиваемую схему.
- **Причины отклонений.** `RecordValidator.validate` возвращает
  `ValidationResult` из `Violation`, называющих поле и правило каждого
  отклонения. Встроенные валидаторы сообщают свои правила, а
  `CompositeValidator.validate` собирает нарушения всех валидаторов.
  Отклонения записываются в журнал вместе с причинами.
- `AsyncEntityExtractor.extract_record(record, text)` и `requires_record` для
  экстракторов, которым нужна запись. Конвейер вызывает `extract_record`.
- `AsyncLLMEntityExtractor.prepare` возвращает текст, отправляемый модели, а
  `stamp` описывает модель, промпт, схему и выпуск библиотеки, стоящие за его
  сущностями. `rejections=` сохраняет отклонённые сущности в хранилище
  отклонений.
- `response_cache_key(schema=, variant=)` и `CachingLLMClient(variant=)`. Схема
  типизированного запроса входит в ключ кэша.
- `sci_etl_core.claims` (предварительно): `Claim`, `ClaimDraft`,
  `EvidenceSpan`, `ExtractionStamp`, `locate_quote`, `AsyncLLMClaimExtractor`,
  хранилища утверждений `InMemoryClaimStore` и `AsyncSqliteClaimStore`,
  `AsyncClaimStoreExporter`, а также хранилища отклонений
  `InMemoryRejectionStore` и `AsyncSqliteRejectionStore`.
- `DeduplicationStep(source_column=)` добавляет столбец `sources` со списком
  различных источников, например `record_id` каждой статьи, всех строк,
  объединённых в каждую выходную строку.
- `ExportError`, `ClaimError` и `ClaimStoreError`.
- Extras `config`, `arxiv`, `xml`, `html` и `processors`.
- `load_config(load_env=True)` и `load_config_async(load_env=True)`.

### Изменено {#changed}

- **Ломающее изменение:** экспортёры получают место назначения при создании и
  реализуют `write(record, entities)` вместо `export(data, destination)`.
  Конвейер больше не принимает `destination`.
- **Ломающее изменение:** конвейер передаёт экспортёру каждую обработанную
  запись, включая запись без сущностей, чтобы экспортёр мог удалить строки,
  которые повторное извлечение больше не находит.
- **Ломающее изменение:** конвейер открывает экспортёр перед первым запросом
  выдачи, сбрасывает его после каждой страницы, а перед сбросом состояния
  сбрасывает и закрывает его, как бы ни закончился запуск. Сбой `open`
  прерывает запуск; сбой `flush` оставляет записи страницы незавершёнными, не
  засчитывая им попытку.
- **Ломающее изменение:** базовая установка требует только `pydantic`.
  Установите extra `config` для `load_config`, `arxiv` для
  `AsyncArxivExtractor`, `xml` для экстрактора PubMed и парсеров JATS и DOCX,
  `html` для `HtmlTextParser` и `processors` для процессоров pandas и табличных
  приёмников.
- **Ломающее изменение:** `load_config` и `load_config_async` читают файл
  `.env` только при передаче `env_path` или `load_env=True`.
- **Ломающее изменение:** каждый модуль пишет журнал через
  `logging.getLogger(__name__)` под логгером `sci_etl_core`, с уровнем
  `WARNING` для неудавшихся и пропущенных записей, `ERROR` для сбоев
  приёмников и состояния и `INFO` для рутинных заметок. Библиотека не
  настраивает обработчики.
- **Ломающее изменение:** `AsyncEntityExtractor` и `AsyncExporter` обобщены
  по типу сущности, а все аргументы `AsyncLLMEntityExtractor` после
  `system_prompt` — только именованные.
- `AsyncLLMClient.invalidate` принимает `schema=` для типизированного запроса.
- Extra `async` больше не устанавливает `aiofiles`, а extra `sql` — `aiosqlite`.
- `AsyncArxivExtractor` повторяет запрос при ответе `406`, а не проваливает
  его, потому что arXiv время от времени возвращает этот код на корректные
  запросы.

### Удалено {#removed}

- Блокирующие интерфейсы `Extractor`, `StateManager`, `Exporter`, `LLMClient`,
  `RelevanceFilter` и `EntityExtractor` и классы `Sync*Adapter`.
- `LegacyExtractorAdapter`.
- `AsyncExporter.export` и аргумент конвейера `destination`.
- `AsyncCsvUpsertExporter`; используйте `AsyncCsvExporter`.
- `AsyncSqlTableExporter` и `AsyncPlotly3DExporter`; используйте `SqlTableSink`
  и `Plotly3DSink`. `ScatterPlotConfig` импортируется из
  `sci_etl_core.processors`.
- Все аргументы `logger=`, `configure_logging` и `AsyncETLPipeline.log`.

## [0.5.1] - 2026-09-26 {#051-2026-09-26}

Этот выпуск не даёт ответам LLM без ответа по существу завершать запись,
не позволяет кэшу LLM воспроизводить их и добавляет ограничения на размер
загрузки и распаковки. Первый запуск после обновления один раз промахивается
мимо кэша LLM. См. раздел «Обновление до 0.5.1» в MIGRATION.md.

### Добавлено {#added_1}

- `AsyncLLMClient.invalidate(system_prompt, user_content)` сообщает об
  отвергнутом ответе, а `AsyncLLMResponseCache.delete(key)` удаляет одну
  запись; оба встроенных кэша его реализуют.
- **Ограничения размера.** `max_download_bytes` у `AsyncArxivExtractor`,
  `AsyncOpenAlexExtractor`, `AsyncPubMedExtractor` и
  `AsyncSemanticScholarExtractor` ограничивает каждое тело ответа после
  декодирования, а `LatexTarballParser(max_tex_bytes=)` ограничивает объём TeX,
  распакованного из одного e-print. Слишком большая страница выдачи вызывает
  `ExtractionError`; слишком большая загрузка полного текста или e-print
  записывается в журнал и пропускается. Оба по умолчанию не ограничены.
- `AsyncArxivExtractor.from_config(full_text=)` строит ограничитель частоты
  экстрактора из раздела конфигурации `full_text`.
- `AsyncOpenAICompatibleClient` и `CachingLLMClient` предоставляют `base_url` и
  `temperature`, а каждый `AsyncLLMClient` предоставляет `response_format`,
  по умолчанию равный `{"type": "json_object"}`. `response_cache_key`
  принимает все три как именованные аргументы.

### Изменено {#changed_1}

- Пустой ответ LLM теперь приводит к неудаче записи, а не завершает её.
  `AsyncOpenAICompatibleClient.complete_json` выбрасывает `LLMError` там, где
  возвращал `{}`, поэтому конвейер повторяет запись при следующем запуске, а не
  помечает её как обработанную, ничего не экспортировав.
- `AsyncLLMEntityExtractor.extract` выбрасывает `LLMError`, когда в ответе нет
  списка сущностей: он пуст или содержит несколько ключей и ни один из них не
  `result_key`. Раньше он возвращал `[]`, и запись помечалась как
  обработанная.
- `AsyncLLMRelevanceFilter` и `AsyncEmbeddingRelevanceFilter` с
  `default_on_error=False` при ошибке закрываются: неудачный вызов или неясный
  вердикт выбрасывает исключение, и запись повторяется при следующем запуске.
  Раньше это считалось нерелевантностью, и запись навсегда помечалась как
  обработанная.
- Ключ кэша LLM теперь включает `base_url` конечной точки, температуру и формат
  ответа, поэтому ответ, закэшированный для одного провайдера, температуры или
  формата, больше не выдаётся для другого. Ответы, закэшированные прежними
  выпусками, не находятся, и первый запуск после обновления вызывает LLM для
  каждого запроса.
- Сторонний `AsyncLLMResponseCache` без `delete` продолжает выдавать ответы,
  которые отвергает библиотека. Реализуйте `delete` или смиритесь с
  повторением.
- `PdfPlumberParser.extract_text` открывает PDF один раз для текста и таблиц,
  тогда как раньше открывал дважды.
- `AsyncSqliteEmbeddingStore.query` работает намного быстрее при повторных
  вызовах. Хранилище держит векторы в памяти и перечитывает их только после
  изменения файла, оценивает их одним произведением NumPy и читает текст и
  метаданные только для возвращаемых фрагментов. Граф связанных статей по
  памяти из 9 000 фрагментов строится примерно в четыре раза быстрее. Теперь
  хранилище держит векторы в памяти между запросами, пока его не закроют.
- Выпуски больше не задерживаются, пока sci-etl-cli и udg-catalogue не начнут
  на них работать; вместо этого готовность потребителей отражается в
  примечаниях к выпуску.

### Исправлено {#fixed}

- `AsyncArxivExtractor` повторяет запрос при тайм-ауте `408`, как и другие
  встроенные экстракторы. Теперь он использует их общий код повторов, поэтому
  его сообщения о повторах и сбоях начинаются с `arXiv` и называют действие,
  например `arXiv LaTeX fetch for '2401.00001v1' failed after 3 attempts`.
- `AsyncSqliteFts5Store.search` выбрасывает `SearchQueryError` с указанием
  версии SQLite, когда SQLite не может подсветить группу `NEAR` с ограничением
  по полю внутри `OR` или `NOT`, как SQLite 3.50.4 делает для некоторых
  документов. Раньше выбрасывался `SearchStoreError` с сообщением «database disk
  image is malformed», которое выглядит как повреждённый индекс.
- `CachingLLMClient` больше не воспроизводит ответ, который отверг экстрактор
  сущностей или фильтр релевантности. Отвергнутый ответ кэшировался, поэтому
  каждая повторная попытка получала тот же ответ, пока запись не попадала в
  карантин, а модель так и не опрашивалась заново.

## [0.5.0] - 2026-09-25 {#050-2026-09-25}

Этот выпуск меняет то, как экстракторы листают выдачу, какое состояние запуска
сохраняется и как создаётся конвейер. Состояние, сохранённое 0.4, обновляется
автоматически. Об изменениях в коде см. раздел «Обновление до 0.5» в
MIGRATION.md.

### Добавлено {#added_2}

- **Листание по курсору.** Экстракторы возвращают из `fetch_page`
  `ListingPage` с курсором следующей страницы. Экстракторы, листающие по
  смещению, также реализуют `OffsetListing`, который требуется запускам
  `newest_first` и `run(start_index=)`.
- **Карантин для записей, которые продолжают проваливаться.**
  `run(max_attempts=3)` пропускает запись, не удавшуюся в 3 запусках.
  `RunMetrics.quarantined` считает пропущенные записи. Оба встроенных
  менеджера состояния хранят число попыток и последнюю ошибку каждой записи.
- **Сообщения о лимитах результатов.** `RunMetrics.listing_truncated`,
  `PageFetched.truncated` и `PipelineMetadata.truncated` показывают, когда
  источник остановился на своём лимите результатов. События прогресса также
  содержат `cursor` страницы.
- **Табличные приёмники.** `SqlTableSink` и `Plotly3DSink` в
  `sci_etl_core.processors.sinks` записывают `DataFrame` после постобработки.
- **Версии схем.** База данных состояния SQLite, кэш LLM, хранилище
  эмбеддингов и файловое состояние записывают версию схемы. Файл, записанный
  более новым выпуском, отвергается, для файлов состояния — с
  `StateStoreError`.
- `StaleCursorError` для курсора, который источник больше не принимает.
- `BaseAppConfig.strict_sections` для отключения строгой валидации
  конфигурации.
- `LegacyExtractorAdapter`, который запускает экстрактор, написанный для 0.4,
  пока его не перенесут. Он уже объявлен устаревшим.

### Изменено {#changed_2}

- **Ломающее изменение:** `AsyncExtractor.fetch_page(query, cursor, page_size)`
  заменяет `search` и `parse_listing`. Теперь конвейер сам пропускает
  обработанные записи.
- **Ломающее изменение:** `PipelineMetadata.cursor` заменяет
  `last_start_index`.
- **Ломающее изменение:** конструкторы конвейеров принимают пять компонентов
  позиционно или по имени, а все остальные аргументы — только по имени.
  `run()` принимает все аргументы после `query` только по имени.
- **Ломающее изменение:** `RawRecord`, `PipelineMetadata`, `TokenUsage`,
  `RunMetrics` и события прогресса нужно создавать с именованными аргументами.
- **Ломающее изменение:** неизвестные ключи в разделах конфигурации
  библиотеки, например `search.bm25.titel`, не проходят валидацию, а не
  игнорируются.
- **Ломающее изменение:** требуется Python 3.11 или новее.
- Запуск, доходящий до лимита результатов источника, теперь завершается, а
  следующий запуск снова начинает с первой страницы, а не останавливается на
  лимите.
- Курсор, отвергнутый источником, один раз перезапускает выдачу с первой
  страницы.
- `AsyncOpenAlexExtractor` листает с помощью курсоров OpenAlex и больше не
  ограничен первыми 10 000 результатами. Он больше не поддерживает
  `newest_first`.
- `AsyncPubMedExtractor` и `AsyncSemanticScholarExtractor` останавливаются на
  последней странице результатов без лишнего пустого запроса.

### Устарело {#deprecated}

Эти имена продолжают работать в 0.5 и удаляются в 0.6.0.

С уже доступной заменой (`DeprecationWarning`):

- блокирующие интерфейсы `Extractor`, `StateManager`, `Exporter`,
  `LLMClient`, `RelevanceFilter` и `EntityExtractor` и классы `Sync*Adapter`;
- `LegacyExtractorAdapter`;
- `AsyncSqlTableExporter` и `AsyncPlotly3DExporter`, заменённые
  `SqlTableSink` и `Plotly3DSink`.

С заменой, которая появится в 0.6.0 (`PendingDeprecationWarning`, так что пока
ничего менять не нужно):

- аргументы `logger=` и `configure_logging`;
- `AsyncETLPipeline(destination=)`;
- `AsyncExporter.export` и `AsyncCsvUpsertExporter`.

### Удалено {#removed_1}

- Ключи конфигурации `pipeline.max_records` и `pipeline.max_workers`,
  соответствующие свойства `PipelineConfig` и `run(max_records=)`. Используйте
  `total_limit` и `max_concurrency`.
- `build_retrying_session`, а также `requests` из extra `full`.

### Исправлено {#fixed_1}

- `AsyncPubMedExtractor` больше не запрашивает результаты дальше 9 999-го,
  которые PubMed отвергает.

## [0.4.1] - 2026-09-25 {#041-2026-09-25}

### Изменено {#changed_3}

- `HttpConfig.user_agent` и `build_async_client` по умолчанию используют
  `sci-etl-core/<installed version>` вместо `sci-etl-core/0.1`.

### Исправлено {#fixed_2}

- `load_config_async` и `AsyncCsvUpsertExporter` проверяют существование файла
  в рабочем потоке, а не блокируют цикл событий.
- Extras `sql` и `full` требуют `sqlalchemy[asyncio]`, поэтому устанавливают
  `greenlet`. SQLAlchemy 2.1 больше не устанавливает его по умолчанию, и без
  него `AsyncSqlTableExporter` не удавалось импортировать.

## [0.4.0] - 2026-09-16 {#040-2026-09-16}

### Добавлено {#added_3}

- `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor` и
  `AsyncOpenAlexExtractor`. Каждый заполняет `RawRecord.metadata` полями
  `authors` и `categories`, а также `published` и `year`, если у источника есть
  дата, и повторяет запросы при сбоях транспорта, `408`, `429` и ошибках
  сервера, соблюдая `Retry-After`. `AsyncOpenAlexExtractor` также сохраняет
  работы, которые цитирует статья, под ключом `references`.
- `DocxParser` для файлов Word `.docx` и `JatsXmlParser` для JATS XML, чей
  `parse_article` возвращает `JatsArticle` с разделами, авторами, ключевыми
  словами, идентификаторами и ссылками.
- Кэширование ответов LLM: `CachingLLMClient` оборачивает любой
  `AsyncLLMClient` и отвечает на повторяющиеся запросы из
  `AsyncLLMResponseCache` — `InMemoryLLMResponseCache` или
  `AsyncSqliteLLMResponseCache`. Сбой кэша записывается в журнал и учитывается в
  `CacheStats`, выбрасывается хранилищами как `LLMCacheError` и никогда не
  приводит к неудаче запроса к модели.
- Корректное завершение: `AsyncETLPipeline(shutdown=)` и
  `ETLPipeline(shutdown=)` принимают `ShutdownSignal`, поэтому SIGINT, SIGTERM
  или `request()` дают завершиться записям в обработке и выбрасывают
  `PipelineInterrupted` — подкласс `PipelineAborted`. Теперь каждый запуск,
  как бы он ни закончился, завершается вызовом `flush()` менеджера состояния.
- События прогресса и метрики запуска: `on_event` получает `RunStarted`,
  `PageFetched`, `RecordFinished`, `PageFinished` и `RunFinished` из
  `sci_etl_core.observability`, а `last_run_metrics` возвращает `RunMetrics` со
  счётчиками, длительностями, исходом запуска и токенами, израсходованными
  `usage_sources`. `TokenUsage` поддерживает `+` и `-`.
- `run(newest_first=True)` подхватывает новые поступления в выдаче «сначала
  новые» без повторного сканирования со смещения 0. В `PipelineMetadata`
  появились `head_ids`, `head_offset` и `tail_ids`, которые сохраняют оба
  бэкенда состояния.
- `rate_limiter` у каждого встроенного экстрактора,
  `AsyncOpenAICompatibleClient` и `AsyncOpenAIEmbedder`, а также
  `HostRateLimiter` для ограничений по хостам.
- Компоненты, создаваемые из конфигурации: `AsyncArxivExtractor.from_config`,
  `AsyncOpenAICompatibleClient.from_config`, `AsyncETLPipeline.from_config` и
  `ETLPipeline.from_config`, а также `HttpConfig.build_client()`,
  `RateLimitConfig.build_limiter()` и `PipelineConfig.run_arguments()`. Раздел
  конфигурации `search` строит `BM25Weights`, `FusionParams`, `HybridParams` и
  `GraphParams`. В `PipelineConfig` появился `newest_first`, а у
  `AsyncOpenAICompatibleClient` — свойство `model`.
- `AsyncLLMEntityExtractor(validator=, logger=, label_field=)` отбрасывает и
  записывает в журнал сущности, которые отвергает `RecordValidator`.
- `ScatterPlotConfig` принимает `hover_data_columns`, `hover_template`,
  `color_continuous_scale`, `color_range`, `color_label`, `marker` и `layout`.
- `ValueClipStep` зажимает числовые столбцы при постобработке, а
  `TableLayoutStep` сортирует строки и упорядочивает столбцы.
- Запросы близости `NEAR(...)` в языке запросов — как узел `Near` с
  `NEAR_DISTANCE`, поддерживаемый обоими текстовыми хранилищами, — и
  `QueryChip.near`.
- Фильтры по диапазонам: `RangeFilter` оставляет записи, теги которых лежат
  между целочисленными или текстовыми границами, например годами или датами
  ISO 8601, в обоих текстовых хранилищах, гибридном поиске и `filter_graph`.
  `AsyncTextSearchStore.range_counts` считает совпадения в каждом из нескольких
  диапазонов. `SearchFilter` обозначает любой из этих типов фильтров.
- Более богатые сниппеты: `TextHit.snippets` и `FusedHit.snippets` содержат
  `Snippet` для каждого поля с подсвеченным совпадением. `passage_snippet` и
  `snippet_window` строят сниппеты для другого текста.
- `backfill_text_index` строит текстовый индекс из фрагментов в векторной
  памяти, удаляя слова, общие для перекрывающихся фрагментов
  (`merge_passages`), и сообщает о проделанном в `BackfillReport`.
  `AsyncEmbeddingStore.iter_records` выдаёт фрагменты каждой записи как
  `StoredRecord`, не загружая векторы; реализован обоими встроенными
  хранилищами.
- `AsyncSimilarArticleFinder.find_best_chunks` возвращает лучший фрагмент
  каждой статьи вместе с текстом. `SlidingWindowChunker` предоставляет
  `chunk_words` и `overlap_words`.

### Изменено {#changed_4}

- `PipelineConfig.max_records` теперь называется `total_limit`, а
  `max_workers` — `max_concurrency`. Старые ключи YAML и атрибуты продолжают
  работать с `DeprecationWarning` до 0.5.0, а загрузка конфигурации, в которой
  старый и новый ключи заданы разными значениями, вызывает
  `ConfigurationError`. `run(max_records=)` устарел так же.
- `build_retrying_session` объявлен устаревшим и будет удалён в 0.5.0 вместе с
  `requests` в extra `full`.
- Результат гибридного поиска, найденный только семантической ветвью, теперь
  несёт сниппет своего лучшего фрагмента в `snippet`, `highlights` и
  `snippets`, тогда как раньше они были пустыми. Коду, который показывал
  аннотацию всякий раз, когда `snippet` был пуст, следует вместо этого
  проверять `lexical_rank is None`.
- `ETLPipeline.run` ждёт фоновый цикл короткими интервалами, поэтому
  обработчик сигналов в вызывающем потоке срабатывает быстро, а
  `KeyboardInterrupt` отменяет запуск в фоновом цикле.

## [0.3.0] - 2026-09-15 {#030-2026-09-15}

### Добавлено {#added_4}

- Локальный булев поиск в `sci_etl_core.search`, которому нужна только
  стандартная библиотека:
  - Язык запросов с терминами, `"фразами"`, префиксными терминами `prefix*`,
    ограничениями `title:`, `abstract:` и `body:`, операторами `AND`, `OR` и
    `NOT` (также записываемыми как `&&`, `||`, `-` или, для `AND`, ничем) и
    скобками. `parse_query` возвращает нормализованное AST, а некорректный
    запрос вызывает `SearchQueryError`, у которого `position` и `token`
    указывают на ошибку. `describe` превращает запрос в метки-чипы для
    отображения.
  - `AsyncSqliteFts5Store` — надёжный текстовый индекс на SQLite FTS5. Он
    ранжирует по BM25 с весами полей `BM25Weights`, возвращает сниппеты в виде
    простого текста со смещениями подсветки, фильтрует по метаданным
    (`MetadataFilter`), считает фасеты по своим `facet_keys` и предлагает для
    обслуживания `optimize`, `rebuild_index`, `rebuild_tags` и
    `integrity_check`. `fts5_available()` сообщает, включает ли SQLite
    интерпретатора FTS5.
  - `InMemoryTextSearchStore`, который находит те же записи, что и хранилище
    FTS5.
  - `AsyncSearchIndexer` — аналог `AsyncChunkIngestor` для текстового индекса.
  - Слияние ранжирований с помощью `reciprocal_rank_fusion` (по умолчанию) или
    `normalized_score_fusion`, настраиваемое через `FusionParams`.
  - `AsyncHybridSearcher`, который выполняет лексический, семантический или
    гибридный поиск и сообщает в `SearchOutcome.degraded` и
    `SearchOutcome.skipped`, какие ветви поиска отказали или были пропущены.
- Графы связанных статей в `sci_etl_core.search`. `build_discovery_graph`
  выращивает окрестность исходной записи в ширину из одного или нескольких
  источников рёбер, по умолчанию оставляет только взаимных ближайших соседей и
  группирует записи в сообщества детерминированным распространением меток.
  `GraphParams` ограничивает глубину, ветвление, минимальный вес ребра, число
  узлов и число проходов распространения меток, а
  `DiscoveryGraph.communities_converged` сообщает, прервал ли лимит проходов
  распространение меток. `filter_graph` сужает построенный граф до найденных
  записей и фильтров по метаданным без какого-либо ввода-вывода.
  `label_communities` и `select_edges` тоже публичны.
- Источники рёбер за новым интерфейсом `AsyncEdgeSource`.
  `EmbeddingEdgeSource` связывает записи по косинусному сходству в векторной
  памяти, а `MetadataEdgeSource` — по доле общих тегов у двух записей,
  например категорий arXiv и авторов.
- `sci_etl_core.discovery` — модель чтения для пользовательских интерфейсов:
  `Facet` и `DiscoveryResult`, экспортируемые также из `sci_etl_core`. Его
  импорт не загружает ни хранилищ, ни необязательных зависимостей.
- `AsyncCompositeIngestor`, который отправляет каждую запись сразу в несколько
  бэкендов памяти, например в векторную память и текстовый индекс, так что сбой
  памяти в одном из них не останавливает остальные.
- `MemoryIngestor` — протокол, которому удовлетворяет `memory_ingestor`, и
  `MEMORY_FAULTS` — исключения, которые конвейер считает сбоями памяти.
- `SearchError` с подклассами `SearchQueryError` и `SearchStoreError`.
- Extra `search`. Он ничего не устанавливает, потому что поиску нужна только
  стандартная библиотека; он позволяет файлу зависимостей указать, зачем нужен
  пакет.

### Изменено {#changed_5}

- `AsyncETLPipeline(memory_ingestor=)` принимает любой `MemoryIngestor`.
  `SearchStoreError` при загрузке в память записывается в журнал, а сущности
  записи всё равно экспортируются, как и при сбое эмбеддингов.
  `SearchQueryError` не является сбоем памяти и приводит к неудаче записи.
- `RawRecord.metadata` больше не пуст для записей arXiv: `AsyncArxivExtractor`
  заполняет его полями `categories`, `authors`, `published` и `year`. Код,
  сравнивавший `metadata == {}`, это заметит. Метаданные фрагментов, которые
  сохраняет `AsyncChunkIngestor`, не изменились.
- `AsyncSqliteEmbeddingStore` работает на общем внутреннем исполнителе SQLite.
  Поведение при этом сохраняется: типы исключений, сообщения, транзакции и
  поведение при отмене не изменились.

### Исправлено {#fixed_3}

- `AsyncSqliteStateManager`: отмена задачи, ожидающей операции с состоянием,
  больше не освобождает соединение, пока его ещё использует рабочий поток.
  Следующая операция ждёт завершения этого потока.

## [0.2.0] - 2026-09-14 {#020-2026-09-14}

### Безопасность {#security}

- `load_config` и `load_config_async` больше не копируют текст ошибки pydantic
  в `ConfigurationError`. Этот текст мог включать сырые настройки, а вместе с
  ними и ключ API, прочитанный из окружения. Теперь сообщение перечисляет
  каждый ошибочный ключ и причину без значения, а ошибка валидации больше не
  связывается с ним в цепочку.

### Добавлено {#added_5}

- `validate_config(config_cls, raw, source)` проверяет настройки, загруженные
  иным способом, с теми же сообщениями, не раскрывающими секретов.
- Поддержка `Retry-After`. `AsyncArxivExtractor`,
  `AsyncOpenAICompatibleClient` и `AsyncOpenAIEmbedder` ждут столько, сколько
  просит ответ с ограничением частоты или ошибкой, — через `Retry-After` или
  заголовок `retry-after-ms`, который отправляют OpenAI-совместимые API, — если
  это дольше их отсрочки. Новый аргумент `max_retry_after` ограничивает ожидание
  (по умолчанию 60 секунд).
- Экстрактор arXiv записывает в журнал каждую повторную попытку и время
  ожидания.
- Расход токенов. `AsyncOpenAICompatibleClient.usage` и
  `AsyncOpenAIEmbedder.usage` возвращают снимок `TokenUsage` с `requests`,
  `prompt_tokens`, `completion_tokens` и `total_tokens`. Свойство `usage` у
  `AsyncLLMClient` и `AsyncEmbedder` возвращает `None`, если его не
  переопределить.
- ruff и mypy запускаются в CI, а extra `lint` устанавливает их локально.
- Этот журнал изменений.

### Изменено {#changed_6}

- Встроенные повторы OpenAI SDK отключены в клиентах чата и эмбеддингов,
  поэтому `max_retries` теперь означает общее число попыток. Раньше SDK мог сам
  повторять каждую из этих попыток.
- Сообщения о некорректных настройках начинаются с
  `Invalid configuration in <file>:` и выводят каждую проблему на отдельной
  строке.
- `AsyncETLPipeline.__aexit__` аннотирован как возвращающий `None`, поэтому
  средства проверки типов знают, что `async with pipeline` никогда не подавляет
  исключение.

## [0.1.2] - 2026-09-14 {#012-2026-09-14}

### Исправлено {#fixed_4}

- `max_concurrency`, равный 0, оставлял каждую запись в вечном ожидании.
  Значения меньше 1 теперь вызывают `ValueError`, как и `page_size` меньше 1 и
  отрицательный `total_limit`.
- Одна неудавшаяся запись на странице с остальными нерелевантными записями
  прерывала весь запуск. Теперь запуск прерывается, только когда вторая
  страница не удаётся без единой обработанной записи до какого-либо прогресса
  или когда выдача заканчивается сразу после такой страницы.
- Конвейер выжидал `sleep_between` ещё раз после достижения `total_limit`.
- `max_retries` меньше 1 приводил к тому, что экстрактор arXiv, клиент LLM и
  эмбеддер проваливались, не сделав ни одной попытки. Теперь это вызывает
  `ValueError`.
- `configure_logging` не работал, если отсутствовала папка файла журнала, и
  игнорировал другой файл или уровень при последующих вызовах.
- `AsyncFileStateManager` молча удалял пробелы из идентификаторов записей,
  поэтому такие записи обрабатывались заново при каждом запуске. Теперь он их
  отвергает, а конвейер пропускает пустые идентификаторы.
- `last_run_at` записывается в UTC со смещением, а не в наивном местном
  времени.

### Добавлено {#added_6}

- `PipelineConfig.page_size` и `PipelineConfig.search_delay`.
- Проверка диапазонов для каждого раздела конфигурации.

### Изменено {#changed_7}

- Процесс выпуска загружает собранные файлы в уже существующий выпуск GitHub,
  а не завершается ошибкой.

## [0.1.1] - 2026-09-14 {#011-2026-09-14}

### Добавлено {#added_7}

- Процесс выпуска, запускаемый тегом, который прогоняет набор тестов CI,
  сверяет тег с версией проекта и публикует в PyPI с помощью доверенной
  публикации.
- Метаданные пакета для PyPI: лицензия, ключевые слова, классификаторы и URL
  проекта.

## [0.1.0] - 2026-09-13 {#010-2026-09-13}

Первый выпуск с тегом: асинхронный конвейер и его блокирующий фасад, экстрактор
arXiv, OpenAI-совместимые клиенты чата и эмбеддингов, парсеры PDF, LaTeX и
HTML, экспортёры CSV, SQL и Plotly, процессоры датафреймов и валидаторы,
файловое состояние и состояние в SQLite, семантическая память и руководство по
миграции udg-catalogue.

[Unreleased]: https://github.com/xueromll/sci-etl-core/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/xueromll/sci-etl-core/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/xueromll/sci-etl-core/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/xueromll/sci-etl-core/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xueromll/sci-etl-core/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xueromll/sci-etl-core/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xueromll/sci-etl-core/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/xueromll/sci-etl-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/xueromll/sci-etl-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xueromll/sci-etl-core/releases/tag/v0.1.0
