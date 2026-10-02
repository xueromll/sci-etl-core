# Быстрый старт

Этот пример ищет в arXiv, спрашивает у LLM, какие статьи релевантны, извлекает
измерения из их полного текста и записывает их в CSV по одной строке на
измерение. Ему нужны extras `async`, `arxiv`, `llm` и `pdf`, а ключ API он
читает из переменной окружения `LLM_API_KEY`, поэтому ключ никогда не
появляется в исходном коде. Чтобы вместо этого загрузить его из файла `.env`,
см. раздел [Конфигурация](configuration.md).

```python
import asyncio
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

RELEVANCE_PROMPT = (
    "Decide whether the paper reports measurements of galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "Extract every measured object from the paper. Reply with JSON: "
    '{"items": [{"name": "...", "value_a": 0.0, "value_b": 0.0}]}.'
)


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(
        api_key=os.environ["LLM_API_KEY"],
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(
            client=client,
            pdf_parser=PdfPlumberParser(),
            latex_parser=LatexTarballParser(),
        ),
        relevance_filter=AsyncLLMRelevanceFilter(
            llm_client=llm, system_prompt=RELEVANCE_PROMPT
        ),
        entity_extractor=AsyncLLMEntityExtractor(
            llm_client=llm, system_prompt=EXTRACTION_PROMPT
        ),
        exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        max_concurrency=4,
        closeables=[client, llm],
    )

    async with pipeline:
        try:
            processed = await pipeline.run("all:galaxy", total_limit=50)
        except PipelineAborted as exc:
            print(f"Stopped early after {exc.partial_count} records: {exc}")
            return
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

## Что делает запуск {#what-a-run-does}

1. Получает страницу выдачи (`page_size` записей, по умолчанию 100) по
   курсору, сохранённому менеджером состояния (или с первой страницы при
   `start_index=0`), и пропускает уже обработанные записи. Страница, на
   которой есть только обработанные записи, пропускается, а не считается
   концом данных.
2. Для каждой оставшейся записи, не более `max_concurrency` одновременно:
   фильтр релевантности → загрузка полного текста → необязательная загрузка в
   память → извлечение сущностей → запись в экспортёр → пометка как
   обработанной. Запись без сущностей тоже записывается, чтобы экспортёр мог
   удалить строки, которые повторное извлечение больше не находит.
   Нерелевантные записи помечаются как обработанные без загрузки полного
   текста. Записи, у которых `record_id` отсутствует или пуст, невозможно
   отследить, поэтому они пропускаются и записываются в журнал.
3. Сбрасывает экспортёр, что делает строки страницы надёжно сохранёнными; у
   экспортёра с буферизацией, такого как `AsyncCsvExporter`, записи
   помечаются как обработанные только сейчас. Затем сохраняет курсор выдачи и
   повторяет, пока не будет обработано `total_limit` релевантных записей или
   не закончится выдача, выжидая `sleep_between` секунд (по умолчанию 0) перед
   каждой следующей страницей. Курсор сдвигается только за страницы, все
   записи которых завершены, а запись, не удавшаяся в 3 запусках, пропускается
   как помещённая в карантин; см.
   [Состояние, возобновление и ошибки](../guide/state.md).

`total_limit` считает только **релевантные** записи, никогда не превышается и
по умолчанию равен `page_size`. Все аргументы `run()` после запроса —
только именованные. `max_concurrency` и `page_size` должны быть не меньше 1, а
`total_limit` не может быть отрицательным; другие значения вызывают
`ValueError` до отправки любого запроса. `AsyncArxivExtractor` также ждёт
`sleep_before_search` секунд (по умолчанию 3) перед каждым запросом выдачи,
чтобы соблюдать ограничения частоты arXiv.

Когда запуск заканчивается, как бы он ни закончился, экспортёр сбрасывается и
закрывается: `AsyncCsvExporter` записывает `results.csv` именно в этот момент,
а во время запуска ведёт `results.csv.journal`. При выходе `async with pipeline`
ожидает `aclose()` у каждого элемента `closeables`, у которого он есть: у
HTTP-клиента, клиента LLM и любых используемых вами `AsyncSqliteStateManager`,
`AsyncSqliteEmbeddingStore` или `AsyncSqliteFts5Store`.

## Промпты должны просить JSON {#prompts-must-ask-for-json}

`AsyncOpenAICompatibleClient` запрашивает режим JSON
(`response_format={"type": "json_object"}`), а API OpenAI отвергает запросы в
режиме JSON, в сообщениях которых ни разу не упоминается «JSON». Формы ответа,
которые читает библиотека:

- `AsyncLLMRelevanceFilter` читает ключ `relevant`. Он принимает булево
  значение, `0`/`1` или строки `"true"`, `"false"`, `"yes"`, `"no"`, `"1"` и
  `"0"` в любом регистре. Всё остальное, включая отсутствие ключа, считается
  ошибкой: запись проходит, или, при `default_on_error=False`, фильтр
  выбрасывает `LLMError` и запись повторяется.
- `AsyncLLMEntityExtractor` читает список под `result_key` (по умолчанию
  `"items"`) или единственное значение, если в ответе ровно один ключ. Список
  должен содержать объекты; `null` означает отсутствие сущностей, а одиночный
  объект считается одной сущностью. Любое другое значение там вызывает
  `LLMError`, и запись повторяется. Пустой ответ, а также ответ с несколькими
  ключами, но без `result_key`, тоже вызывают `LLMError`, поэтому называйте
  ключ в промпте.
- `AsyncCsvExporter` записывает ключи, перечисленные в `columns`, в отдельные
  столбцы, а все остальные ключи — в столбец `extra` в виде JSON, так что ни
  одно значение не теряется. Передайте модель Pydantic как `schema=`, чтобы
  проверять каждую сущность; см.
  [Типизированные сущности](../guide/typed-entities.md).

## Дальнейшие шаги {#next-steps}

- Запустите тот же конвейер из синхронного кода с помощью
  [`ETLPipeline`](blocking-usage.md).
- Загружайте настройки из YAML и `.env` с помощью
  [типизированной конфигурации](configuration.md).
- Сохраняйте статью и предложение-доказательство для каждого значения с помощью
  [утверждений и происхождения](../guide/claims.md).
- Очищайте и стройте графики по CSV с помощью
  [шагов постобработки](../guide/post-processing.md).
