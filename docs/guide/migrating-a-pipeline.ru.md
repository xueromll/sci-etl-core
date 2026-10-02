# Перенос пайплайна

Это руководство переносит существующий исследовательский пайплайн на
`sci-etl-core`, используя в качестве разобранного примера одну реальную
миграцию: [udg-catalogue](https://github.com/xueromll/udg-catalogue), который
с помощью LLM строит каталог ультрадиффузных галактик (UDG) по статьям из
arXiv.

Каждый фрагмент «до» взят из udg-catalogue в том виде, в каком он был до
миграции. Каждый фрагмент «после» в шагах 1–9 взят из перенесённого проекта на
sci-etl-core 0.2, на
[коммите `8cd9471`](https://github.com/xueromll/udg-catalogue/tree/8cd94711b864212a8fa0d55d60f51e500cf42ec3).
Некоторые из этих вызовов 0.2 с тех пор были переименованы или удалены.
Раздел [К чему вы придёте](#where-youll-end-up) показывает проект на 0.6, а
раздел [Обновление проекта](#upgrading-the-project) показывает, как менялся код
в [ветке `main`](https://github.com/xueromll/udg-catalogue/tree/main) проекта
при переходе на 0.4, 0.5 и 0.6.
[Руководство по миграции](../project/migration.md) перечисляет все изменения по
релизам. Предметная область здесь — астрономия, но ничто в шагах от неё не
зависит: замените промпты, поля и правила предметной области своими.

- [Проект до миграции](#the-project-before)
- [К чему вы придёте](#where-youll-end-up)
- [Сопоставьте свой пайплайн с библиотекой](#map-your-pipeline-onto-the-library)
- [Шаг 1: установите и подключите библиотеку](#step-1-install-and-link-the-library)
- [Шаг 2: конфигурация и секреты](#step-2-configuration-and-secrets)
- [Шаг 3: источник и полный текст](#step-3-source-and-full-text)
- [Шаг 4: шаги с LLM](#step-4-the-llm-steps)
- [Шаг 5: правила предметной области как плагины](#step-5-domain-rules-as-plug-ins)
- [Шаг 6: экспорт и состояние](#step-6-export-and-state)
- [Шаг 7: постобработка](#step-7-post-processing)
- [Шаг 8: проверьте совпадение результатов, прежде чем менять поведение](#step-8-check-parity-before-changing-behavior)
- [Шаг 9: удалите старый код](#step-9-delete-the-old-code)
- [Обновление проекта](#upgrading-the-project)
- [Что обнаружила миграция](#what-the-migration-uncovered)
- [Адаптация к вашей области](#adapting-this-to-your-field)

---

## Проект до миграции {#the-project-before}

udg-catalogue ищет в arXiv `cat:astro-ph.GA AND abs:ultra-diffuse`. Для
каждой статьи он спрашивает у LLM, сообщает ли аннотация о реальных
наблюдениях, загружает исходник LaTeX или PDF, просит LLM извлечь каждую
галактику в виде JSON и объединяет галактики в CSV. Затем шаг постобработки
удаляет дубликаты, оценивает полноту, назначает созвездия и трёхмерные
кластеры и записывает отсортированный каталог, на котором работает панель
мониторинга Streamlit.

Механизм ETL жил в плоских модулях в корне проекта:

| Модуль | Строк | Ответственность |
|--------|-------|-----------------|
| `arxiv_client.py` | 198 | поиск в arXiv и разбор Atom, загрузка LaTeX и PDF, извлечение таблиц, отсечение списка литературы, оба вызова LLM |
| `data_processor.py` | 314 | файл обработанных идентификаторов, валидация галактик, upsert в CSV, дедупликация, полнота, созвездия, кластеризация, флаги качества |
| `main.py` | 94 | цикл пагинации поверх `ThreadPoolExecutor` |
| `config.py`, `logger.py`, `incremental.py` | 97 | чтение YAML в константы модуля, настройка журналирования, смещение для возобновления |

Цикл оркестрации в `main.py` выглядел так:

```python
while papers_processed < MAX_PAPERS:
    xml_data = search_arxiv(SEARCH_QUERY, max_results=MAX_PAPERS, start_index=start_index)
    if not xml_data:
        break
    papers, total_in_xml = parse_arxiv_xml(xml_data, processed_ids)
    if total_in_xml == 0 or not papers:
        break

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_paper_task, paper, processed_ids): paper for paper in papers}
        for future in as_completed(futures):
            try:
                success = future.result()
                if success:
                    papers_processed += 1
                if papers_processed >= MAX_PAPERS:
                    break
            except Exception as exc:
                logger.error(f"Paper processing generated an exception: {exc}")

    start_index += MAX_PAPERS
    save_pipeline_metadata(start_index)
    time.sleep(SLEEP_BETWEEN)
```

## К чему вы придёте {#where-youll-end-up}

После миграции вся сторона загрузки данных — это несколько функций, которые
связывают между собой компоненты библиотеки. Вот `udg_catalogue/pipeline.py`
на sci-etl-core 0.6, сокращённый до пайплайна загрузки и без обёрток,
журналирующих прогресс:

```python
def build_catalogue_exporter(config: CatalogueConfig) -> AsyncCsvExporter:
    return AsyncCsvExporter(config.paths.raw_catalogue, [KEY_COLUMN, *MEASUREMENT_FIELDS])


def build_entity_extractor(
    config: CatalogueConfig,
    llm_client: AsyncLLMClient,
    rejections: AsyncRejectionStore | None = None,
) -> AsyncLLMEntityExtractor[dict[str, Any]]:
    return AsyncLLMEntityExtractor(
        llm_client,
        EXTRACTION_PROMPT,
        result_key=EXTRACTION_RESULT_KEY,
        timeout=config.llm.timeout,
        validator=build_galaxy_validator(),
        rejections=rejections,
        label_field=KEY_COLUMN,
    )


def build_pipeline(config, logger, http_client, llm_client, library, shutdown=None):
    cache = AsyncSqliteLLMResponseCache(config.paths.llm_cache)
    cached_llm = CachingLLMClient(llm_client, cache, model=config.llm.model)
    rejections = AsyncSqliteRejectionStore(config.paths.rejections)
    extractor = AsyncArxivExtractor.from_config(
        config.http,
        config.pipeline,
        client=http_client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        full_text=config.full_text,
    )
    return AsyncETLPipeline.from_config(
        config.pipeline,
        extractor=extractor,
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=cached_llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=build_entity_extractor(config, cached_llm, rejections),
        exporter=build_catalogue_exporter(config),
        state_manager=AsyncFileStateManager(config.paths.processed_ids, config.paths.pipeline_metadata),
        closeables=[http_client, llm_client, cache, rejections, *library.closeables],
        memory_ingestor=library.memory_ingestor(build_chunker(config.embeddings)),
        shutdown=shutdown,
        on_event=PipelineEventLogger(logger.info, logger.warning),
        usage_sources=[llm_client, *library.usage_sources],
    )


async def run_ingestion(config, logger, start_index=None, shutdown=None) -> int:
    library = open_paper_library(config)
    http_client = build_http_client(config)
    llm_client = build_llm_client(config)
    async with build_pipeline(config, logger, http_client, llm_client, library, shutdown) as pipeline:
        return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

`build_pipeline` принимает HTTP- и LLM-клиенты аргументами, поэтому тесты
проекта передают `httpx.MockTransport`, отдающий фиктивную ленту Atom и
e-print, плюс заскриптованный `AsyncLLMClient`, и запускают настоящий пайплайн
офлайн.

`main.py` сжимается до загрузки конфигурации, запуска загрузки и построения
результатов:

```python
config = load_catalogue_config(arguments.config)
log = configure_run_logging(config.paths.log_file)
processed = asyncio.run(run_ingestion(config, log, start_index, ShutdownSignal()))
catalogue = build_sorted_catalogue(config, log.info, replace=arguments.replace_catalogue)
write_manifest(config, log.info)
```

В проекте остаётся то, что может написать только астроном: промпты, правила
именования и валидации галактик, сопоставление по положению на небе, признаки
для кластеризации и панель мониторинга.

## Сопоставьте свой пайплайн с библиотекой {#map-your-pipeline-onto-the-library}

Начните с того, что распределите каждую функцию старого пайплайна по одной из
трёх групп: заменяется компонентом библиотеки, заменяется компонентом
библиотеки плюс небольшим плагином или остаётся.

| До (udg-catalogue) | После | Что вы всё ещё пишете сами |
|--------------------|-------|----------------------------|
| `search_arxiv`, `parse_arxiv_xml` | `AsyncArxivExtractor` | ничего |
| `fetch_paper_text`, `extract_tables_from_pdf`, `trim_references` | `AsyncArxivExtractor` с `LatexTarballParser` и `PdfPlumberParser` | ничего |
| сессия `requests` с `Retry` | `build_async_client` | ничего |
| `is_paper_relevant` | `AsyncLLMRelevanceFilter` | промпт |
| `extract_udg_data` | `AsyncLLMEntityExtractor(result_key="galaxies")` | промпт |
| клиент OpenAI, направленный на DeepSeek | `AsyncOpenAICompatibleClient` | базовый URL и модель |
| `upsert_to_csv` | `AsyncCsvExporter`, затем `DeduplicationStep` при постобработке | список столбцов |
| `load_processed_ids`, `save_processed_id`, `incremental.py` | `AsyncFileStateManager` | пути к файлам |
| цикл в `main.py` | `AsyncETLPipeline` | связывание, показанное выше |
| `logger.py` | стандартный модуль `logging` | обработчики для журнала запуска |
| `config.py` | подкласс `BaseAppConfig` и `load_config` | настройки проекта |
| `universal_normalize_name` | подкласс `KeyNormalizer` | правила сопоставления имён |
| `is_valid_galaxy` | `RecordValidator`, переданные в `AsyncLLMEntityExtractor(validator=)` | правила для полей |
| `clean_duplicates` | `NormalizationStep` и `DeduplicationStep` | `NeighborMatcher` для положений на небе |
| `calculate_completeness`, `assign_quality_flag` | `CompletenessStep`, `QualityFlagStep` | список полей |
| `assign_3d_clusters` | `ClusteringStep` | `FeatureExtractor` для трёхмерных положений |
| `assign_constellations`, графики, панель мониторинга | остаются | код предметной области, по возможности в виде `Processor` |

Таблица называет компоненты sci-etl-core 0.6. Шаги 1–9 показывают компоненты
0.2, которые udg-catalogue использовал в то время, например экспортёр CSV с
upsert и обёртку экстрактора с валидацией, которые позже были заменены.

## Шаг 1: установите и подключите библиотеку {#step-1-install-and-link-the-library}

Во время миграции вы будете менять обе кодовые базы, поэтому установите
библиотеку в редактируемом режиме в окружение проекта. udg-catalogue
находится в двух папках от своего клона sci-etl-core:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "../../sci-etl-core[async,llm,pdf,cluster]"
python -c "import sci_etl_core; print(sci_etl_core.__file__)"
```

В Windows активируйте окружение командой `.venv\Scripts\activate`. Последняя
команда должна напечатать путь внутри папки `src` клона. Выберите extras для
используемых компонентов: udg-catalogue нужен `async` для экстрактора arXiv и
экспортёра CSV, `llm` для OpenAI-совместимого клиента, `pdf` для
`PdfPlumberParser` и `cluster` для `ClusteringStep`.

Редактируемая установка запоминает абсолютный путь к клону. Если переместить
или переименовать папку библиотеки, `import sci_etl_core` перестанет работать,
пока вы не переустановите её; именно это произошло, когда рабочее пространство
udg-catalogue переехало в синхронизируемую папку OneDrive.

Развёрнутые окружения не видят соседний клон, а pip не может установить один
пакет из двух источников в одном разрешении зависимостей. Поэтому udg-catalogue
держит свои закреплённые сторонние пакеты в `requirements-app.txt` и выбирает
источник библиотеки в двух тонких файлах. Для локальной разработки —
`requirements-local.txt`:

```text
-r requirements-app.txt
-e ../../sci-etl-core[async,llm,pdf,cluster]
```

Для Docker, CI и новых пользователей `requirements.txt` устанавливает
опубликованный релиз из PyPI:

```text
-r requirements-app.txt
sci-etl-core[async,llm,pdf,cluster]>=0.2.0,<0.3
```

Закрепляйте диапазон версий, а не одну точную версию, чтобы исправляющие
релизы приходили без изменения проекта, и поднимайте верхнюю границу
осознанно, проверив новый минорный релиз на своих тестах. До того как
библиотека появилась в PyPI, udg-catalogue коммитил wheel, собранный командой
`pip wheel --no-deps -w vendor path/to/sci-etl-core`, и устанавливал его из
`vendor/`; это по-прежнему работает для сборки, у которой нет доступа к PyPI.

## Шаг 2: конфигурация и секреты {#step-2-configuration-and-secrets}

**До** (`config.py`): YAML читался в константы уровня модуля при импорте
модуля.

```python
load_dotenv()
API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg: dict = yaml.safe_load(f)

MODEL: str = cfg.get("model", "deepseek-v4-flash")
CSV_FILE: str = os.path.join(SCRIPT_DIR, cfg.get("csv_file", "udg_database.csv"))
MAX_PAPERS: int = cfg.get("max_papers", 500)
```

**После**: `config.yaml` использует разделы библиотеки (`llm`, `http`,
`pipeline`) плюс собственные разделы проекта (`paths`, `clustering`,
`deduplication`):

```yaml
llm:
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  timeout: 120

http:
  user_agent: "UDG-ResearchScript/1.0 (lanhua1122333@gmail.com)"
  max_retries: 4
  backoff_factor: 5.0
  timeout: 25

pipeline:
  search_query: "cat:astro-ph.GA AND abs:ultra-diffuse"
  max_records: 500
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_workers: 6

paths:
  raw_catalogue: "udg_database.csv"
  sorted_catalogue: "udg_database_sorted.csv"
  processed_ids: "processed_arxiv_ids.txt"
  pipeline_metadata: "pipeline_meta.json"

clustering:
  max_distance_mpc: 5.0
  min_samples: 2

deduplication:
  max_separation_arcsec: 3.0
```

`udg_catalogue/config.py` наследует модели библиотеки:

```python
class CataloguePipelineConfig(PipelineConfig):
    page_size: int = 100
    search_delay: float = 3.0


class CatalogueConfig(BaseAppConfig):
    pipeline: CataloguePipelineConfig = Field(default_factory=CataloguePipelineConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    deduplication: DeduplicationConfig = Field(default_factory=DeduplicationConfig)


def load_catalogue_config(config_path: Path = DEFAULT_CONFIG_PATH) -> CatalogueConfig:
    resolved = Path(config_path).resolve()
    config = load_config(
        CatalogueConfig,
        resolved,
        resolved.parent / ".env",
        api_key_env_var=API_KEY_ENV_VAR,
    )
    return config.model_copy(update={"paths": config.paths.anchored_at(resolved.parent)})
```

Здесь стоит перенять три решения:

- **Сохраните имя своего секрета.** `api_key_env_var="DEEPSEEK_API_KEY"`
  означает, что существующий файл `.env` и файл Docker Compose продолжают
  работать без изменений. Ключ хранится как `SecretStr`, поэтому он никогда
  не появляется в repr и журналах.
- **Расширяйте разделы наследованием.** `CataloguePipelineConfig` добавляет
  `page_size` и `search_delay`, сохраняя все поля, которые читает библиотека.
- **Разрешайте пути относительно файла конфигурации.** Явная передача `.env`,
  лежащего рядом с конфигурацией, и привязка относительных путей к папке
  конфигурации означают, что пайплайн ведёт себя одинаково, из какого бы
  каталога вы его ни запускали. Старый код разрешал большинство путей
  относительно папки скрипта, а `pipeline_meta.json` и `analysis/` —
  относительно рабочего каталога.

Значения конфигурации не применяются автоматически: передавайте их в
конструкторы и в `run()`, как это делает `build_pipeline`.

## Шаг 3: источник и полный текст {#step-3-source-and-full-text}

**До** (`arxiv_client.py`, в сокращении):

```python
def search_arxiv(query: str, max_results: int = 5, start_index: int = 0) -> bytes | None:
    ...
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(base_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=(10, 60))
            if response.status_code == 429:
                time.sleep(20)
                continue
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(5 * (attempt + 1))
            else:
                logger.error(f"arXiv search failed after {MAX_RETRIES} attempts: {e}")
    return None


def fetch_paper_text(entry: dict) -> str:
    ...
    with session.get(source_url, headers={"User-Agent": USER_AGENT}, timeout=25, verify=False, stream=True) as r:
        ...
```

**После**:

```python
extractor = AsyncArxivExtractor(
    client=http_client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    max_retries=config.http.max_retries,
    backoff_factor=config.http.backoff_factor,
    sleep_before_search=config.pipeline.search_delay,
    logger=logger.info,
)
```

Что изменилось в поведении:

- **Неудавшийся поиск — это ошибка, а не конец данных.** `search_arxiv`
  возвращал `None`, а цикл в `main.py` воспринимал это как «статей больше
  нет» и сообщал об успехе. Старый журнал показывает 9 запусков, которые
  остановились таким образом. Теперь `AsyncETLPipeline.run()` выбрасывает
  `PipelineAborted`, а `main.py` завершается с кодом 1.
- **Повторы ждут дольше значений по умолчанию.** Экстрактор ждёт
  `backoff_factor ** attempt` секунд между попытками, поэтому множитель по
  умолчанию, равный 2, ждёт 1 с, а затем 2 с. arXiv ограничивает частоту
  ответом `429` дольше этого, а старый код после 429 ждал 20 с, поэтому
  udg-catalogue устанавливает `backoff_factor: 5.0` и `max_retries: 4`
  (ожидания 1, 5 и 25 с).
- **Проверка TLS снова включена.** Старая загрузка e-print использовала
  `verify=False`.
- **Больше поступлений дают LaTeX.** Одиночный сжатый gzip файл `.tex`
  читается, а не приводит к переходу на PDF, а многофайловые исходники
  собираются в порядке `\input`.
- **Всё остальное осталось прежним.** Шаблоны отсечения списка литературы — те
  же семь выражений, а парсер PDF добавляет таблицы под тем же маркером
  `--- EXTRACTED TABLES ---`. Для трёх недавних статей старый и новый код
  вернули побайтно одинаковый текст.

## Шаг 4: шаги с LLM {#step-4-the-llm-steps}

**До** (`arxiv_client.py`, в сокращении):

```python
def is_paper_relevant(title: str, abstract: str) -> bool:
    if not abstract:
        return True
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": STRICT_SIMULATION_PROMPT},
                {"role": "user", "content": f"Title: {title}\nAbstract: {abstract}"}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=20
        )
        data = json.loads(response.choices[0].message.content.strip())
        return bool(data.get("relevant", False))
    except Exception as e:
        logger.warning(f"Filter error: {e}. Proceeding to download.")
        return True


def extract_udg_data(text: str | bytes) -> list[dict]:
    try:
        ...
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return []
```

**После** (те же вызовы, что в `run_ingestion` и `build_pipeline`, вынесенные
в переменные):

```python
llm_client = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    default_timeout=config.llm.timeout,
)
relevance_filter = AsyncLLMRelevanceFilter(llm_client=llm_client, system_prompt=RELEVANCE_PROMPT)
entity_extractor = AsyncLLMEntityExtractor(
    llm_client=llm_client,
    system_prompt=EXTRACTION_PROMPT,
    result_key="galaxies",
    timeout=config.llm.timeout,
)
```

Промпты переехали в `udg_catalogue/prompts.py` символ в символ. В них уже
упоминался JSON, чего требует режим JSON, а промпт извлечения уже просил
`{"galaxies": [...]}`, поэтому `result_key="galaxies"` читает именно эту форму,
и промпт менять не пришлось. Ограничение в 120 000 символов, удаление HTML и
температура 0 тоже являются значениями по умолчанию библиотеки.

Что изменилось в поведении:

- **Релевантность по-прежнему пропускает при ошибке.** Неудавшийся вызов, как и
  раньше, пропускает статью, а тайм-аут по-прежнему 20 с. Одно отличие: ответ
  без однозначного вердикта теперь тоже пропускает статью, тогда как старый код
  считал отсутствующий ключ `relevant` равным `False`. Передайте
  `default_on_error=False`, чтобы вместо этого задерживать такие статьи;
  начиная с 0.5.1 они тогда повторяются при следующем запуске.
- **Неудачи извлечения повторяются.** `extract_udg_data` возвращал `[]`, когда
  DeepSeek давал сбой, поэтому статья помечалась как обработанная, хотя ничего
  не было извлечено; старый журнал показывает 8 таких статей, к которым никто
  никогда не вернётся. `AsyncLLMEntityExtractor` выбрасывает `LLMError`,
  пайплайн оставляет статью непомеченной, и следующий запуск пробует её снова.

## Шаг 5: правила предметной области как плагины {#step-5-domain-rules-as-plug-ins}

Правила, решающие, что считать одной и той же галактикой и что считать
настоящей галактикой, — это наука, и они остаются в проекте. Библиотека даёт им
место для подключения.

### Сопоставление имён: `KeyNormalizer` {#name-matching-a-keynormalizer}

**До** (`data_processor.py`):

```python
def universal_normalize_name(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    digits_match = re.search(r"\d+", s)
    if digits_match:
        digits = str(int(digits_match.group()))
        if s.startswith("vcc"):
            return f"vcc{digits}"
        return f"dragonfly{digits}"

    return s
```

Сначала перенесите подобную функцию **без изменений**, в виде подкласса
`KeyNormalizer`, чтобы проверка совпадения на шаге 8 сравнивала только обвязку и
ничего больше. udg-catalogue поступил именно так.

Оказалось, что эта функция объединяет разные галактики (см.
[Что обнаружила миграция](#what-the-migration-uncovered)), поэтому её заменили,
как только совпадение результатов было подтверждено. **После**
(`udg_catalogue/naming.py`):

```python
DEFAULT_PREFIX_ALIASES: dict[str, str] = {"dragonfly": "df"}
_NAME_TOKEN = re.compile(r"[^\W\d_]+|\d+")
_NUMBER_SEPARATOR = "."


class GalaxyNameNormalizer(KeyNormalizer):
    def __init__(self, prefix_aliases: Mapping[str, str] | None = None) -> None:
        self._prefix_aliases = dict(DEFAULT_PREFIX_ALIASES if prefix_aliases is None else prefix_aliases)
        self._missing_value_guard = DefaultKeyNormalizer()

    def normalize(self, raw_value: Any) -> str:
        if not self._missing_value_guard.normalize(raw_value):
            return ""
        tokens = _NAME_TOKEN.findall(unicodedata.normalize("NFKC", str(raw_value)).casefold())
        if not tokens:
            return ""
        tokens[0] = self._prefix_aliases.get(tokens[0], tokens[0])
        key: list[str] = []
        previous_is_number = False
        for token in tokens:
            is_number = token.isdecimal()
            if is_number and previous_is_number:
                key.append(_NUMBER_SEPARATOR)
            key.append(str(int(token)) if is_number else token)
            previous_is_number = is_number
        return "".join(key)
```

`DF 44`, `DF044` и `Dragonfly 44` по-прежнему получают общий ключ `df44`, а
`KDG 44`, `NGC 1052-DF2` и `NGC 1052-DF4` теперь сохраняют собственные ключи.
Делегирование проверки отсутствующего значения `DefaultKeyNormalizer` означает,
что `None`, `NaN` и нескалярные значения обрабатываются так, как ожидает каждый
компонент библиотеки. И экспортёр CSV, и дедупликация при постобработке
используют `GalaxyNameNormalizer`, поэтому оба этапа всегда согласны в том, что
считать одним объектом.

### Валидация: `RecordValidator` и обёртка {#validation-recordvalidators-and-a-wrapper}

**До** (`data_processor.py`): валидация была спрятана внутри `upsert_to_csv`.

```python
def is_valid_galaxy(galaxy: dict) -> bool:
    ...
    if FORBIDDEN_PATTERN.search(name):
        logger.info(f"Object '{name}' filtered out as simulation/model.")
        return False

    ra, dec = galaxy.get("ra"), galaxy.get("dec")
    if ra is not None:
        try:
            if not (0.0 <= float(ra) <= 360.0):
                return False
        except (ValueError, TypeError):
            return False
    ...
    return any(galaxy.get(f) is not None for f in KEY_FIELDS)
```

**После** (`udg_catalogue/validation.py`): валидаторы библиотеки покрывают
правила по ключевым словам и диапазонам, а остальное покрывает один небольшой
класс.

```python
class HasAnyMeasurement(RecordValidator):
    def __init__(self, fields: Iterable[str]) -> None:
        self._fields = tuple(fields)

    def is_valid(self, record: dict[str, Any]) -> bool:
        return any(record.get(field) is not None for field in self._fields)


def build_galaxy_validator() -> RecordValidator:
    return CompositeValidator(
        [
            KeywordExclusionValidator(KEY_COLUMN, list(SIMULATION_KEYWORDS)),
            NumericRangeValidator(SKY_COORDINATE_RANGES),
            HasAnyMeasurement(MEASUREMENT_FIELDS),
        ]
    )
```

`AsyncETLPipeline` сам не вызывает валидаторы, поэтому тонкий
`AsyncEntityExtractor` применяет их между извлечением и экспортом и записывает
в журнал то, что отбрасывает:

```python
class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(
        self,
        inner: AsyncEntityExtractor,
        validator: RecordValidator,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self._inner = inner
        self._validator = validator
        self._log = logger or (lambda _message: None)

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        for entity in await self._inner.extract(text):
            if self._validator.is_valid(entity):
                accepted.append(entity)
            else:
                self._log(f"Entity rejected by validation: {entity.get(KEY_COLUMN)!r}")
        return accepted
```

Прежде чем полагаться на `KeywordExclusionValidator` вместо старого регулярного
выражения, сверьте их на своих существующих данных. Для udg-catalogue они
совпали на всех 1 285 сохранённых именах и на пограничных случаях, таких как
`TNG50-1`, `illustris_galaxy_1` и `Firefly 7`.

## Шаг 6: экспорт и состояние {#step-6-export-and-state}

**До** (`data_processor.py` и `incremental.py`, в сокращении): каждый рабочий
поток читал весь CSV, менял его и записывал обратно без какой-либо блокировки
между шестью потоками.

```python
def upsert_to_csv(records: list[dict]) -> None:
    ...
    df = pd.read_csv(CSV_FILE) if os.path.isfile(CSV_FILE) and os.path.getsize(CSV_FILE) > 0 else pd.DataFrame(columns=fieldnames)
    ...
    df.drop(columns=["_norm_name"]).to_csv(CSV_FILE, index=False, encoding="utf-8")


def save_processed_id(arxiv_id: str) -> None:
    if arxiv_id:
        with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
            f.write(arxiv_id + "\n")


def save_pipeline_metadata(start_index: int) -> None:
    meta = {"last_run_date": datetime.now().isoformat(), "last_start_index": start_index}
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4)
```

**После** (`build_catalogue_exporter` и менеджер состояния из
`build_pipeline`, с константами из `udg_catalogue/config.py` и выписанными
путями по умолчанию):

```python
exporter = AsyncCsvUpsertExporter(
    key_column="galaxy_name",
    value_columns=["ra", "dec", "distance_mpc", "effective_radius_kpc", "stellar_mass_solar", "dark_matter_fraction"],
    normalizer=GalaxyNameNormalizer(),
    numeric_clip={"dark_matter_fraction": (0.0, 1.0)},
)
state_manager = AsyncFileStateManager("processed_arxiv_ids.txt", "pipeline_meta.json")
```

Экспортёр сохраняет старое правило слияния: одна строка на нормализованное имя,
более поздние записи только заполняют пустые ячейки, значения приводятся к
числам с плавающей точкой, а `numeric_clip` заменяет написанное вручную
зажатие доли тёмной материи. Он также сериализует параллельный экспорт и
публикует каждый снимок атомарным переименованием.

**Проверьте, можно ли использовать существующие файлы состояния как есть.**
У udg-catalogue это получилось: `processed_arxiv_ids.txt` уже содержал голые
идентификаторы с версией, например `2607.14209v1`, — в формате, который
выдаёт `AsyncArxivExtractor`, а в `pipeline_meta.json` уже были ключи
`last_run_date` и `last_start_index`, которые читает `AsyncFileStateManager`.
Направив менеджер состояния на старые файлы, удалось перенести все 542
обработанные статьи без скрипта импорта. Если ваши идентификаторы хранятся в
виде URL или без суффикса версии, сначала преобразуйте их, иначе все статьи
будут обработаны заново.

Две детали возобновления изменились:

- **Выдачи «сначала новые».** arXiv выдаёт сначала самые новые поступления,
  поэтому сохранённое смещение «уплывает» по мере появления новых статей.
  Теперь `main.py` по умолчанию передаёт `start_index=0`, заново сканируя с
  самого нового поступления и пропуская обработанные статьи по
  идентификатору; повторное сканирование стоит запросов листинга, а не вызовов
  LLM. `python main.py --resume` вместо этого использует сохранённое
  смещение.
- **Смещения сдвигаются только за устоявшиеся страницы.** Старый цикл прибавлял
  к смещению 500 после каждой страницы, даже если статьи на ней не удались.
  Библиотека сдвигается за страницу, только когда каждая статья на ней
  обработана или признана нерелевантной.

## Шаг 7: постобработка {#step-7-post-processing}

**До** (`data_processor.py`, в сокращении): дедупликация переписывала сырой CSV
на месте, предварительно сделав копию `.bak`, а `process_database` выполнял
последовательность функций.

```python
def process_database() -> None:
    df = pd.read_csv(CSV_FILE)
    ...
    if "dark_matter_fraction" in df.columns:
        df["dark_matter_fraction"] = df["dark_matter_fraction"].clip(0.0, 1.0)

    df = calculate_completeness(df)
    df = assign_constellations(df)
    df = assign_3d_clusters(df)
    df = assign_quality_flag(df)
    ...
    df_sorted.to_csv(SORTED_CSV_FILE, index=False, encoding="utf-8")
```

**После** (`udg_catalogue/postprocess.py`): та же последовательность в виде
`ProcessorChain`, при этом сырой CSV остаётся нетронутым, а записывается только
отсортированный каталог.

```python
def build_catalogue_chain(config: CatalogueConfig, normalizer: KeyNormalizer | None = None) -> ProcessorChain:
    return ProcessorChain(
        [
            NormalizationStep(KEY_COLUMN, normalizer or GalaxyNameNormalizer(), NORMALIZED_KEY_COLUMN),
            DeduplicationStep(
                NORMALIZED_KEY_COLUMN,
                matcher=SkyPositionMatcher(),
                match_threshold=config.deduplication.max_separation_arcsec,
            ),
            ValueClipStep(FRACTION_BOUNDS),
            CompletenessStep(list(MEASUREMENT_FIELDS)),
            ConstellationStep(),
            ClusteringStep(
                CartesianDistanceFeatures(),
                eps=config.clustering.max_distance_mpc,
                min_samples=config.clustering.min_samples,
            ),
            QualityFlagStep(),
            CatalogueLayoutStep(),
        ]
    )
```

`CompletenessStep`, `QualityFlagStep`, `NormalizationStep`,
`DeduplicationStep` и `ClusteringStep` взяты из библиотеки. Наука подключается
через два небольших интерфейса. `SkyPositionMatcher` сообщает
`DeduplicationStep`, какие строки являются одним и тем же объектом на небе:

```python
class SkyPositionMatcher(NeighborMatcher):
    def find_matches(self, frame: pd.DataFrame, threshold: float) -> list[tuple[int, int]]:
        located = frame[located_rows(frame, self._ra_column, self._dec_column)]
        if len(located) < 2:
            return []
        coordinates = sky_coordinates(located, self._ra_column, self._dec_column)
        neighbours, separations, _ = coordinates.match_to_catalog_sky(coordinates, nthneighbor=2)
        separation_arcsec = separations.to_value(u.arcsec)
        labels = located.index.to_numpy()
        return [
            (int(labels[position]), int(labels[neighbour]))
            for position, neighbour in enumerate(neighbours)
            if separation_arcsec[position] <= threshold and labels[position] < labels[neighbour]
        ]
```

`CartesianDistanceFeatures` даёт `ClusteringStep` трёхмерные положения,
построенные по прямому восхождению, склонению и расстоянию.
`ConstellationStep`, `ValueClipStep` и `CatalogueLayoutStep` — обычные
`Processor`, оставшиеся в проекте: `Processor` должен лишь возвращать новый
DataFrame, не изменяя входной.

Хранение сырого CSV как источника истины для экспортёра и получение из него
отсортированного файла делает постобработку воспроизводимой:
`python main.py --skip-ingestion` перестраивает все результаты, не обращаясь
ни к arXiv, ни к LLM.

## Шаг 8: проверьте совпадение результатов, прежде чем менять поведение {#step-8-check-parity-before-changing-behavior}

Держите старый код запускаемым рядом с новым и подавайте обоим одинаковые
входные данные. Устанавливать старый проект не нужно: выгрузите старые модули
из Git во временную папку командой `git show <commit>:data_processor.py` и
импортируйте их оттуда.

udg-catalogue провёл четыре проверки.

**Повтор экспорта.** Каждую строку существующего каталога случайным образом
разбили на две частичные записи извлечения, добавили несколько написанных
вручную некорректных записей и подали перемешанные записи пакетами и через
старый upsert, и через новые валидатор и экспортёр:

```python
for batch in batches:
    data_processor.upsert_to_csv([dict(record) for record in batch])

for batch in batches:
    await exporter.export([record for record in batch if validator.is_valid(record)], "new.csv")
```

**Постобработка.** Старые `clean_duplicates` и `process_database` и новая
цепочка выполнялись на копиях одного и того же сырого каталога, а
отсортированные результаты сравнивались ячейка за ячейкой. Сравнивайте
*состав* кластеров, а не их идентификаторы: DBSCAN нумерует кластеры в порядке,
в котором их встречает.

**Полный текст.** Старая и новая загрузка получили одни и те же три недавние
статьи.

**Живой запуск.** Собранный пайплайн запускался против arXiv и DeepSeek с
небольшими `page_size` и `total_limit` в новую папку состояния.

| Проверка | Результат |
|----------|-----------|
| Повтор экспорта: 2 581 запись в 735 пакетах | идентичный CSV |
| Повтор экспорта с галактикой, повторяющейся в одной статье | идентичный после слияния 2 строк-дубликатов, созданных старым upsert |
| Постобработка каталога из 1 285 галактик | идентичный ячейка в ячейку, включая порядок строк и идентификаторы кластеров, кроме 3 строк, у которых RA больше 360° |
| Полный текст для 3 недавних статей | побайтно идентичный текст LaTeX |
| Живой запуск | arXiv отвечал `429` на каждую попытку запроса листинга, и `run()` выбросил `PipelineAborted`, ничего не записав, вместо того чтобы сообщить об успехе; именно это побудило увеличить задержку на шаге 3 |
| Набор тестов проекта | 84 офлайн-теста, покрытие 100 %, проходят и с редактируемой библиотекой, и в чистом окружении, установленном из встроенного в репозиторий wheel |

Только после того, как всё это совпало, исправление нормализатора было внесено
отдельным изменением. При перестроении отсортированного каталога с ним
единственными различиями оказались три строки с некорректным RA,
перенумерованные кластеры с неизменным составом и удалённый столбец
`filled_fields`.

Когда вы запускаете перенесённый пайплайн:

- Ищите в журнале `Record processing failed`. Эти записи не были помечены как
  обработанные, и следующий запуск повторит их.
- Если `run()` выбрасывает `PipelineAborted`, прочитайте `__cause__`
  исключения: там видны отвергнутый ключ API, нечитаемый CSV или запрос
  листинга, упёршийся в ограничение частоты.
- Если вы писали собственные компоненты, сверьте их с контрактами в разделе
  [Добавление нового компонента](../project/contributing.md#adding-a-new-component).

## Шаг 9: удалите старый код {#step-9-delete-the-old-code}

Когда проверки пройдены, удалите то, что заменила библиотека. udg-catalogue
удалил `arxiv_client.py`, `data_processor.py`, `config.py`, `logger.py`,
`incremental.py`, продублированный шаблон ключевых слов симуляций и
неиспользуемый промпт фильтра, вместе с тестами, которые подменяли `requests` и
пул потоков. Остались пакет `udg_catalogue` из модулей предметной области
(конфигурация, промпты, именование, валидация, астрометрия, постобработка,
карты, аналитика) и набор тестов, который прогоняет настоящий пайплайн офлайн.

`visualization.py` и панель мониторинга раньше строили одну и ту же фигуру
Plotly дважды; миграция стала удобным моментом, чтобы дать им один общий
построитель фигуры. `AsyncPlotly3DExporter` не использовался, потому что
карте udg-catalogue нужны собственные всплывающие подсказки и фиксированный
диапазон цветов.

## Обновление проекта {#upgrading-the-project}

На шаге 1 закрепляется диапазон версий, а его верхняя граница поднимается только
после проверки нового минорного релиза на тестах проекта.
[Руководство по миграции](../project/migration.md) перечисляет, что меняет
каждый релиз; в этом разделе записано, что эти изменения означали для
udg-catalogue.

### Переход на 0.4 {#moving-to-04}

udg-catalogue пропустил 0.3: его `build_pipeline` не передавал
`memory_ingestor`, а `AsyncFileStateManager` не изменился, поэтому ничто в 0.3
его не затронуло. Он перешёл с `>=0.2.0,<0.3` сразу на `>=0.4.0,<0.5`, добавив
extras `embeddings`, `embeddings-local` и `search`:

```text
sci-etl-core[async,llm,pdf,cluster,embeddings,embeddings-local,search]>=0.4.0,<0.5
```

Обновление до 0.4 избавило от нескольких фрагментов кода, которые шаги выше
заставили проект написать:

- **Переименованные настройки пайплайна.** `build_pipeline` и `run_ingestion`
  из 0.2 выдают предупреждения на 0.4, потому что `max_records` и
  `max_workers` стали `total_limit` и `max_concurrency`. udg-catalogue
  переименовал оба ключа в `config.yaml`.
- **Никакого подкласса пайплайна.** В `PipelineConfig` появились `page_size`,
  `search_delay` и `newest_first`, поэтому `CataloguePipelineConfig` из шага 2
  был удалён, и `CatalogueConfig` использует раздел `pipeline` библиотеки как
  есть.
- **Валидация без обёртки.** udg-catalogue передаёт `build_galaxy_validator()`
  и `label_field=KEY_COLUMN` в `AsyncLLMEntityExtractor` и удалил
  `ValidatedEntityExtractor` из шага 5.
- **Возобновление «сначала новые».** udg-catalogue устанавливает
  `pipeline.newest_first: true`, поэтому `python main.py` теперь по умолчанию
  возобновляет работу; флага `--resume` из шага 6 больше нет, а `--rescan`
  передаёт `start_index=0` с `newest_first=False`, чтобы пролистать весь
  листинг.
- **Кэширование, завершение и сводки запусков.** udg-catalogue оборачивает свой
  LLM-клиент в `CachingLLMClient` поверх `AsyncSqliteLLMResponseCache`, поэтому
  повторный запуск после сбоя не платит дважды за те же вызовы релевантности и
  извлечения. Он передаёт `ShutdownSignal`, а `main.py` завершается с кодом 130
  при `PipelineInterrupted`. Обратный вызов `on_event` записывает в журнал
  каждый `PageFinished`, а `RunMetrics` события `RunFinished`, включая расход
  токенов из `usage_sources`, становится сводкой запуска в журнале.
- **Графики.** `ScatterPlotConfig` получил собственные всплывающие подсказки и
  фиксированный диапазон цветов, из-за отсутствия которых udg-catalogue на шаге
  9 не использовал `AsyncPlotly3DExporter`.
- **Зажатие и раскладка таблицы.** udg-catalogue удалил свои собственные
  `ValueClipStep` и `CatalogueLayoutStep` из шага 7; цепочка теперь
  импортирует `ValueClipStep` из библиотеки и заканчивается
  `TableLayoutStep(sort_by=SORT_ORDER, leading_columns=LEADING_COLUMNS,
  hidden_prefixes=("_",))`.

После обновления связывание пайплайна udg-catalogue читает настройки из
конфигурации и индексирует каждую релевантную статью для поиска. В сокращении
до ветви загрузки `udg_catalogue/pipeline.py` строит пайплайн так:

```python
def build_pipeline(config, logger, http_client, llm_client, library, shutdown=None):
    cache = AsyncSqliteLLMResponseCache(config.paths.llm_cache)
    cached_llm = CachingLLMClient(llm_client, cache, model=config.llm.model, logger=logger.warning)
    extractor = AsyncArxivExtractor.from_config(
        config.http,
        config.pipeline,
        client=http_client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        logger=logger.info,
    )
    return AsyncETLPipeline.from_config(
        config.pipeline,
        extractor=extractor,
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=cached_llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=build_entity_extractor(config, cached_llm, logger),
        exporter=build_catalogue_exporter(),
        state_manager=AsyncFileStateManager(config.paths.processed_ids, config.paths.pipeline_metadata),
        destination=str(config.paths.raw_catalogue),
        logger=logger.warning,
        closeables=[http_client, llm_client, cache, *library.closeables],
        memory_ingestor=library.memory_ingestor(build_chunker(config.embeddings), logger.warning),
        shutdown=shutdown,
        on_event=progress_logger(logger.info),
        usage_sources=[llm_client, *library.usage_sources],
    )
```

`library.memory_ingestor` возвращает `AsyncCompositeIngestor`, который сохраняет
чанки с эмбеддингами в `AsyncSqliteEmbeddingStore` и индексирует статью в
`AsyncSqliteFts5Store`, или только `AsyncSearchIndexer`, когда
`embeddings.enabled` равно false. Сам запуск сжимается до одного блока
`async with`:

```python
async def _run(build, config, logger, start_index, shutdown):
    library = open_paper_library(config)
    http_client = build_http_client(config)
    llm_client = build_llm_client(config)
    async with build(config, logger, http_client, llm_client, library, shutdown) as pipeline:
        return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

Статьи, отобранные до обновления, никогда не индексировались, а векторной памяти
для заполнения у udg-catalogue не было. `python main.py --index-papers` заново
получает их через тот же пайплайн с экстрактором сущностей, который ничего не
возвращает, фильтром релевантности, пропускающим статьи, уже имеющиеся в
текстовом индексе, и отдельным менеджером состояния (`indexed_arxiv_ids.txt`,
`indexing_meta.json`), так что каталог галактик и его обработанные
идентификаторы остаются нетронутыми.

### Переход на 0.5 {#moving-to-05}

udg-catalogue перешёл на `>=0.5.1,<0.6`. Его затронули два изменения:

- **Строгая конфигурация.** Разделы конфигурации библиотеки отвергают
  неизвестные ключи, и udg-catalogue сделал строгими и свои разделы (`paths`,
  `embeddings`, `clustering`, `deduplication`), так что опечатка в
  `config.yaml` приводит к ошибке при запуске с названием ключа. Имена 0.2
  `max_records` и `max_workers` больше не загружаются.
- **Разобранные страницы листинга.** Экстракторы возвращают `ListingPage` из
  `fetch_page(query, cursor, page_size)` вместо сырых байтов из `search` и
  `parse_listing`, поэтому обёртка проекта, журналирующая каждый запрос
  листинга, теперь пробрасывает `cursor_for_offset` и `fetch_page`.

### Переход на 0.6 {#moving-to-06}

udg-catalogue перешёл на `>=0.6.0,<0.7`. Начиная с 0.6 базовой установке нужен
только Pydantic, поэтому проект перечисляет каждый импортируемый им extra,
добавив `config` (YAML и `.env`), `arxiv` (разбор Atom), `html` и `processors`
(pandas):

```text
sci-etl-core[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]>=0.6.0,<0.7
```

Остальная часть обновления изменила то, что записывает каталог:

- **Одна строка на галактику на статью.** `AsyncCsvUpsertExporter` больше нет.
  `AsyncCsvExporter` пишет по одной строке на галактику, помеченной `record_id`
  статьи, никогда не объединяет, не обрезает и не приводит значения и заменяет
  строки статьи, когда статья извлекается снова. Всё объединение перенесено в
  постобработку. В сыром каталоге, записанном 0.5, нет столбца `record_id`,
  поэтому каталог один раз перестраивается с нуля, а постобработка отказывается
  принимать старый сырой файл с сообщением об этом.
- **Статьи за каждой галактикой.** Цепочка постобработки начинается с
  небольшого `RawRowsStep`, который скрывает `record_id` и `extra` как
  `_record_id` и `_extra` и читает измерения как числа. Затем
  `DeduplicationStep(source_column="_record_id", sources_column="source_papers")`
  перечисляет статьи, объединённые в каждую галактику, в опубликованном
  каталоге.
- **Отклонения с причинами, сохранённые для проверки.**
  `GalaxyValidator.validate` возвращает `Violation`, код которого называет
  нарушенное правило (`no-name`, `paper-local-name`, `simulation-keyword`,
  `not-a-number`, `not-positive`, `out-of-range` или `no-measurement`), там,
  где `is_valid` говорил лишь `False`. Экстрактор записывает в журнал каждое
  отклонение с причиной и сохраняет его в `AsyncSqliteRejectionStore`, где
  рецензент может просмотреть его и вынести решение.
- **Стандартное журналирование.** Аргументов `logger=` и `configure_logging`
  больше нет. `configure_run_logging` проекта подключает обработчики журнала
  запуска к собственному логгеру проекта и к `sci_etl_core`, а
  `logging.Filter` добавляет к строкам библиотеки префикс с идентификатором
  arXiv обрабатываемой статьи.
- **Индексирование никогда не трогает каталог.** Запуск `--index-papers`
  передавал экспортёр каталога вместе с экстрактором, который ничего не
  возвращает. Начиная с 0.6 пайплайн записывает каждую обработанную запись,
  включая запись без сущностей, и такая запись очищает строки этой статьи.
  Поэтому пайплайн индексирования получает экспортёр, который ничего не
  сохраняет:

    ```python
    class DiscardingExporter(AsyncExporter[Any]):
        async def write(self, record: RawRecord, entities: Sequence[Any]) -> None:
            return None
    ```

- **Манифест запуска.** После каждой сборки `write_manifest` записывает в
  `data/run_manifest.json` версию sci-etl-core, модель и базовый URL, хэши
  обоих промптов, запрос, обработанные идентификаторы arXiv, а также число
  строк и SHA-256 обоих каталогов; этот файл коммитится рядом с опубликованным
  каталогом.

## Что обнаружила миграция {#what-the-migration-uncovered}

Перенос кода на общие компоненты заставляет точно формулировать каждое
правило. Миграция udg-catalogue выявила следующие проблемы, большинство из
которых не было видно в старом выводе:

1. **Сопоставление имён объединяло разные галактики.** Старый нормализатор
   превращал любое имя с цифрами, кроме имён VCC, в ключ
   `dragonfly<первое число>`: 1 201 из 1 285 сохранённых имён (93 %). `KDG 44`
   совпадало с `DF 44`, а `NGC 1052-DF2` — с `NGC 1052-DF4`, поэтому upsert
   молча заполнял пробелы одной галактики измерениями другой. Исправленный
   нормализатор сохраняет различными все 1 285 сохранённых имён, но строки,
   объединённые прежними запусками, можно разделить только повторным
   извлечением каталога.
2. **Сбои выглядели как успех.** Девять сбоев поиска arXiv завершили запуски
   так, будто листинг исчерпан, а 8 ошибок DeepSeek пометили статьи как
   обработанные, хотя ничего не было извлечено.
3. **Параллельная запись CSV шла без блокировки.** Шесть потоков переписывали
   один и тот же CSV, и журнал фиксирует 8 исключений рабочих потоков в этом
   цикле.
4. **Проверка TLS была отключена** для загрузки e-print.
5. **Upsert дублировал галактики**, названные дважды в извлечении из одной
   статьи; это нашёл только повтор экспорта.
6. **У трёх сохранённых галактик RA больше 360°.** Старый шаг созвездий молча
   заворачивал их по кругу; теперь о них сообщается как об `Unknown`.
7. **Закреплённые зависимости невозможно было установить** на той версии
   Python, которую называл README: у `numpy==1.22.0` нет wheel для Python 3.11,
   а `pandas==2.0.0` там требует более новый numpy.
8. **Редактируемая установка сломалась** после переезда рабочего пространства в
   другую папку.

## Адаптация к вашей области {#adapting-this-to-your-field}

- [ ] Перечислите все функции своего пайплайна и распределите их по трём
      группам из раздела [Сопоставьте свой пайплайн с библиотекой](#map-your-pipeline-onto-the-library).
- [ ] Установите библиотеку в редактируемом режиме и решите, как её будут
      получать развёртывания (диапазон версий из PyPI или встроенный в
      репозиторий wheel там, где PyPI недоступен).
- [ ] Перенесите настройки в разделы `BaseAppConfig`; сохраните имя переменной
      окружения ключа API с помощью `api_key_env_var`.
- [ ] Перенесите промпты без изменений и задайте в `result_key` ключ списка,
      который уже запрашивает ваш промпт извлечения.
- [ ] Перенесите правило сопоставления имён в виде `KeyNormalizer`, а правила
      для записей — в виде `RecordValidator`, поначалу без изменений.
- [ ] Прежде чем писать скрипт импорта, проверьте, не соответствуют ли уже ваши
      файлы обработанных идентификаторов и смещений формату менеджера
      состояния.
- [ ] Выразите постобработку как `ProcessorChain`, поместив логику предметной
      области в плагины `NeighborMatcher`, `FeatureExtractor` и `Processor`.
- [ ] Прогоните реальные данные через старый и новый код и сравните
      результаты.
- [ ] Только после этого исправляйте правила, которые оказались неудачными, по
      одному коммиту за раз.
- [ ] Удалите старый код и тесты, которые покрывали только его.

Есть вопросы или шероховатость в вашей миграции? Откройте
[issue](https://github.com/xueromll/sci-etl-core/issues) — мы будем рады помочь.
