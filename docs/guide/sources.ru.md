# Поддерживаемые источники

У каждого источника свой протокол, модель постраничной выдачи, схема
идентификаторов и форматы полного текста, поэтому каждый получает собственный
`AsyncExtractor`, а не один экстрактор с переключателями для каждого источника.

| Источник | Экстрактор | Идентификатор записи | Постраничность | Полный текст |
|----------|------------|----------------------|----------------|--------------|
| arXiv | `AsyncArxivExtractor` | идентификатор arXiv с версией | смещения | исходник LaTeX, затем PDF, затем аннотация |
| PubMed | `AsyncPubMedExtractor` | PMID | смещения, первые 9 999 результатов | JATS из PubMed Central, если у статьи есть идентификатор PMC, иначе аннотация |
| Semantic Scholar | `AsyncSemanticScholarExtractor` | идентификатор статьи | смещения, первые 1 000 результатов | PDF в открытом доступе при наличии `pdf_parser`, иначе аннотация |
| OpenAlex | `AsyncOpenAlexExtractor` | идентификатор работы, например `W2741809807` | курсоры OpenAlex, без лимита | PDF в открытом доступе при наличии `pdf_parser`, иначе аннотация |
| bioRxiv, ChemRxiv | Нет в комплекте | | | Адаптируйте `AsyncArxivExtractor` |
| Crossref | Нет в комплекте | | | Реализуйте собственный `AsyncExtractor` |

Экстрактор, который листает по смещению, является `OffsetListing`; это нужно
для запусков `newest_first` и для `run(start_index=)` больше 0. Когда источник
останавливается на собственном лимите результатов, его экстрактор помечает
страницу, достигшую лимита, как `truncated`: запуск завершается, и следующий
запуск снова листает доступные результаты, а не останавливается на лимите.
Обработанные записи пропускаются по идентификатору, поэтому такое повторное
сканирование стоит запросов выдачи, а не вызовов LLM. Чтобы его избежать,
сузьте запрос, например диапазоном дат. Подробности — в разделе
[Семантика запуска](run-semantics.md#capped-listings).

Встроенные экстракторы разделяют поведение повторов, описанное в разделе
[Повторные попытки](retries.md), и принимают `rate_limiter`
([Ограничение частоты запросов](rate-limiting.md)). Каждый также принимает
`max_download_bytes`, который ограничивает каждое тело ответа после
декодирования: слишком большая страница выдачи вызывает `ExtractionError`, а
слишком большая загрузка полного текста записывается в журнал и пропускается.
`LatexTarballParser(max_tex_bytes=)` так же ограничивает объём TeX,
распакованного из одного e-print arXiv. Каждый экстрактор заполняет
`RawRecord.metadata` полями `authors` и `categories`, а также `published` и
`year`, если у источника есть дата, поэтому фильтры поиска и фасеты одинаково
работают для всех источников. Источники, кроме arXiv, также сохраняют там
`pdf_url` или `pmcid`, которые читает `fetch_full_text`.

## PubMed {#pubmed}

```python
from sci_etl_core import AsyncPubMedExtractor
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncPubMedExtractor(
    client,
    api_key=ncbi_api_key,
    tool="my-project",
    email="you@example.org",
    rate_limiter=build_rate_limiter(max_rate=9, time_period=1.0),
)
await pipeline.run("dark matter[tiab] AND 2020:2026[dp]", total_limit=200, newest_first=True)
```

Запрос использует синтаксис поиска PubMed. Результаты идут от новых к старым
(`sort="pub_date"`), поэтому подходит `newest_first=True`. Каждая страница
выдачи стоит двух запросов, а NCBI разрешает 3 запроса в секунду без ключа API
и 10 с ключом, поэтому читайте ключ из окружения и задайте ограничитель ниже
этого значения. E-utilities листает первые 9 999 результатов поиска даже через
свой сервер истории, поэтому страница, которая до них доходит, помечается как
`truncated`. Метаданные добавляют `journal`, а также `doi` и `pmcid`, если они
известны; `categories` — это рубрики MeSH.

## Semantic Scholar {#semantic-scholar}

```python
from sci_etl_core import AsyncSemanticScholarExtractor
from sci_etl_core.parsers import PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncSemanticScholarExtractor(
    client,
    PdfPlumberParser(),
    api_key=semantic_scholar_key,
    year="2020-",
    fields_of_study="Physics",
    rate_limiter=build_rate_limiter(max_rate=1, time_period=1.0),
)
```

Поиск по релевантности возвращает только первые 1 000 результатов и не
упорядочен по дате, поэтому запускайте его без `newest_first`; страница,
доходящая до 1 000-го результата, помечается как `truncated`. Метаданные
добавляют `venue`, а также `doi`, `arxiv_id` и `pmid`, если они известны.

## OpenAlex {#openalex}

```python
from sci_etl_core import AsyncOpenAlexExtractor

extractor = AsyncOpenAlexExtractor(
    client,
    filter="type:article,from_publication_date:2020-01-01",
    mailto="you@example.org",
)
await pipeline.run("ultra-diffuse galaxies", total_limit=500)
```

По умолчанию результаты идут от новых к старым
(`sort="publication_date:desc"`). Постраничность использует курсоры OpenAlex,
поэтому выдача не ограничена первыми 10 000 результатами, но экстрактор не
является `OffsetListing` и не поддерживает запуски `newest_first`. Когда запуск
доходит до конца выдачи, следующий запуск снова начинает с первой страницы и
пропускает обработанные работы по идентификатору. Курсор, который OpenAlex
отвергает, один раз перезапускает выдачу. `mailto` включает вас в «вежливый
пул» OpenAlex. Аннотации восстанавливаются из инвертированного индекса
OpenAlex. Метаданные добавляют `doi`, `venue` и `references` — идентификаторы
работ, которые цитирует статья.

## Форматы документов {#document-formats}

Помимо парсеров PDF, LaTeX и HTML, которые используют экстракторы, два парсера
читают форматы, которые вы можете получить из других источников:

- **`DocxParser`** читает файлы Word `.docx` с помощью стандартной библиотеки
  и `lxml`: абзацы по порядку, таблицы — как строки, разделённые табуляцией, а
  с `include_notes=True` — ещё и сноски и концевые сноски.
- **`JatsXmlParser`** читает JATS XML — формат PubMed Central и многих
  издателей. `extract_text` возвращает заголовок, аннотацию и основной текст
  без списка литературы, а `parse_article` возвращает `JatsArticle` с
  разделами, авторами, ключевыми словами, журналом, датой публикации,
  идентификаторами и ссылками.

```python
from sci_etl_core.parsers import JatsXmlParser

article = JatsXmlParser().parse_article(xml_bytes)
print(article.title, article.doi, [section.title for section in article.sections])
```

Оба разбирают XML, не разрешая сущности и не загружая DTD, и вызывают
`ParsingError` для байтов, которые не могут прочитать.

## Написание экстрактора {#writing-an-extractor}

Конвейер работает с любым классом, реализующим этот контракт:

```python
from sci_etl_core import AsyncExtractor, ListingPage
from sci_etl_core.models import RawRecord


class MySourceExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...
```

- **`fetch_page`** получает и разбирает одну страницу. `cursor=None` — первая
  страница; любой другой курсор — это `next_cursor`, который вернула одна из
  предыдущих страниц, возможно, в предыдущем запуске. Метод возвращает
  `ListingPage` со всеми записями, которые удалось прочитать, числом элементов
  на странице, включая те, что прочитать не удалось, и следующим курсором или
  `None` на последней странице. Обработанные записи конвейер пропускает сам.
  Источник, остановившийся на собственном лимите результатов, возвращает
  `truncated=True`.
- Ошибки: если источник недоступен, выбрасывайте `UpstreamError`, а не
  возвращайте пустую страницу; если он прямо отвергает запрос, выбрасывайте
  `ExtractionError`; если полезную нагрузку не удаётся прочитать,
  выбрасывайте `MalformedResponseError`. Каждая из них прерывает запуск. Если
  источник больше не принимает курсор, выбрасывайте `StaleCursorError`, и
  запуск один раз перезапустит выдачу с первой страницы.
- **`cursor_for_offset`** нужен только источнику, который листает по смещению.
  Он делает экстрактор `OffsetListing`; не реализуйте его, если курсоры —
  непрозрачные токены.
- **`fetch_full_text`** возвращает лучший доступный текст для записи.

Полный контракт для каждого типа компонентов приведён в разделе
[Добавление нового компонента](../project/contributing.md#adding-a-new-component),
а [справочник API экстракторов](../reference/extractors.md) документирует
базовые классы.
