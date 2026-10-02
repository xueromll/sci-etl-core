# Ранжированный поиск и фильтрация

Хранилища принимают разобранные запросы, а `AsyncHybridSearcher` принимает
текст и разбирает его один раз, до любого ввода-вывода. Ранжированному поиску
нужен термин, по которому ранжировать, поэтому запрос, в котором все термины
отрицаются, например `NOT simulation` или `NOT simulation OR quasar`, вызывает
`SearchQueryError` из `search`. Вместо этого используйте `filter_ids`. Он
принимает любой запрос и возвращает `frozenset` идентификаторов записей,
который не несёт порядка, а значит, его нельзя принять за ранжирование:

```python
from sci_etl_core.search import parse_query

hits = await text_store.search(parse_query("photometr* dwarf"), limit=20)
observational = await text_store.filter_ids(parse_query("NOT simulation"))
```

У `TextHit` есть `score`, где больше — лучше. Его шкала зависит от корпуса,
поэтому сравнивайте оценки только в пределах одного списка результатов.

## Сниппеты {#snippets}

`snippet` результата — это простой текст из поля, которое совпало лучше всего,
а `highlights` содержит символьные смещения `[start, end)` найденных слов в
нём, чтобы интерфейс применял собственную разметку. Поле длиннее 24 токенов
обрезается до окна в 24 токена вокруг совпадения, с `…` на месте пропущенного
текста.

Когда запрос совпадает в нескольких полях, `snippets` содержит по `Snippet`
для каждого из них в порядке `title`, `abstract`, `body`, так что результат
может показать совпадение в заголовке и фрагмент из основного текста вместе:

```python
from sci_etl_core.search import parse_query

for hit in await text_store.search(parse_query("dwarf OR photometr*"), limit=10):
    for snippet in hit.snippets:
        marked = [snippet.text[start:end] for start, end in snippet.highlights]
        print(f"{hit.record_id} {snippet.field}: {snippet.text} {marked}")
```

Поле попадает в `snippets`, только когда в нём подсвечено найденное слово.
Оба текстовых хранилища подсвечивают одни и те же слова, кроме запросов, в
которых FTS5 учитывает ещё и слово внутри части запроса, не давшей
совпадения; это описано в документации `InMemoryTextSearchStore`.

`passage_snippet(query, text)` таким же образом строит `Snippet` для любого
другого текста, подсвечивая каждое слово запроса, которое не отрицается.
Гибридный поиск использует его для чанков, найденных семантической ветвью.
