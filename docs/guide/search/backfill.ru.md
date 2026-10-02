# Заполнение из векторной памяти

Развёртывание, которое работало с семантической памятью, но без текстового
индекса, уже хранит полный текст каждой релевантной записи, разбитый на
фрагменты, в своём `AsyncSqliteEmbeddingStore`. `backfill_text_index` строит
текстовый индекс из этих фрагментов, так что ничего не нужно заново загружать
или пересчитывать в эмбеддинги:

```python
import asyncio

from sci_etl_core.embeddings import AsyncSqliteEmbeddingStore, SlidingWindowChunker
from sci_etl_core.search import AsyncSqliteFts5Store, backfill_text_index


async def backfill() -> None:
    vector_store = AsyncSqliteEmbeddingStore("memory.db")
    text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))
    try:
        report = await backfill_text_index(
            vector_store,
            text_store,
            overlap_words=SlidingWindowChunker().overlap_words,
        )
        print(f"{report.indexed} indexed, {report.skipped_existing} already there, {report.skipped_empty} empty")
    finally:
        await vector_store.aclose()
        await text_store.aclose()


asyncio.run(backfill())
```

Запустите его один раз, пока ни один конвейер не пишет ни в одно из
хранилищ, а затем добавьте в конвейер `AsyncSearchIndexer`, как показано в
разделе [Локальный поиск и обзор](index.md), чтобы новые записи
индексировались по мере поступления.

## Перекрывающиеся фрагменты {#overlapping-chunks}

`SlidingWindowChunker` перекрывает соседние фрагменты, по умолчанию на 50 слов,
чтобы ни один отрывок не обрывался на границе окна. Если соединить фрагменты как
есть, эти слова повторятся, и BM25 посчитает каждое слово на границе дважды.
Заполнение убирает перекрытие с помощью `merge_passages`, которая отбрасывает
первые `overlap_words` слов каждого фрагмента, когда они повторяют конец
предыдущего, так что основной текст восстанавливается с каждым словом по
одному разу.

Передайте `overlap_words` того разбивщика, который записал фрагменты. С
`SlidingWindowChunker(chunk_words, overlap_words)` передайте тот же
`overlap_words`; если вы его не указывали, прочитайте значение у разбивщика,
созданного так же, как это делает пример. Фрагмент, первые слова которого не
повторяют последние слова предыдущего, сохраняется целиком, поэтому неверное
значение оставит повторённые слова в тексте, а не вырежет его часть.

Основной текст восстанавливается с одиночными пробелами между словами, как его
разбил разбивщик; переносы строк и интервалы между абзацами пропадают, что не
меняет совпадений.

## Что содержит заполненный документ {#what-a-backfilled-document-holds}

Векторная память хранит меньше, чем было у конвейера, поэтому по умолчанию у
заполненного документа есть:

| Поле | Значение |
|------|----------|
| `title` | `title`, сохранённый вместе с фрагментами записи |
| `abstract` | пусто, поскольку фрагменты его не содержат |
| `body` | объединённые фрагменты |
| `metadata` | остальные метаданные фрагментов, например `source_url` |

`AsyncChunkIngestor` не сохраняет `RawRecord.metadata` вместе с фрагментами,
поэтому у заполненного документа нет `categories`, `year` и других тегов
фасетов, и фильтры по этим ключам его не находят. Если эти метаданные есть у
вас в другом месте, например в экспортированном CSV, передайте
`build_document`, который их добавит. Он получает `StoredRecord` и
объединённый текст и возвращает `SearchDocument` для индексирования или
`None`, чтобы пропустить запись:

```python
from sci_etl_core.search import SearchDocument, backfill_text_index, stored_record_document


def with_catalogue_metadata(record, body):
    document = stored_record_document(record, body)
    if document is None or record.record_id not in catalogue:
        return document
    entry = catalogue[record.record_id]
    document.abstract = entry["abstract"]
    document.metadata.update(categories=entry["categories"], year=entry["year"])
    return document


report = await backfill_text_index(
    vector_store, text_store, overlap_words=50, build_document=with_catalogue_metadata
)
```

## Записи, уже находящиеся в индексе {#records-already-in-the-index}

У записи, которую конвейер уже проиндексировал, есть аннотация и метаданные,
которых нет у заполненного документа, поэтому заполнение её не трогает и
учитывает в `skipped_existing`. Передайте `replace_existing=True`, чтобы
перезаписать каждую запись из векторной памяти, например после того, как
текстовый индекс был построен заново с нуля. Записи текстового индекса,
которых нет в векторной памяти, никогда не затрагиваются.

- **Пакеты.** Записи читаются и пишутся по `batch_size` за раз (по умолчанию
  100), без загрузки векторов, поэтому расход памяти остаётся ровным даже на
  большом хранилище.
- **Другие векторные хранилища.** `InMemoryEmbeddingStore` и
  `AsyncSqliteEmbeddingStore` умеют перечислять свои записи через
  `iter_records`. Собственный `AsyncEmbeddingStore`, который его не реализует,
  вызывает `NotImplementedError`.
- **Владение.** `backfill_text_index` не закрывает ни одно из хранилищ;
  закрывайте их сами, как это делает пример.
