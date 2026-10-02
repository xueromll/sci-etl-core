# Локальный поиск и обзор

Текстовый индекс рядом с векторной памятью добавляет булев поиск, гибридный
поиск, объединяющий ранжирования по ключевым словам и по смыслу, фасеты
метаданных и графы связанных статей. Всё это находится в `sci_etl_core.search`
и требует только `sqlite3` из стандартной библиотеки, поэтому работает при
голой установке `pip install sci-etl-core`. Extra `search` ничего не
устанавливает; он лишь позволяет файлу зависимостей указать, зачем нужен пакет.
Extra `embeddings` нужен только семантической стороне.

## Индексирование из пайплайна {#indexing-from-the-pipeline}

Этот пример расширяет пример из раздела [Семантическая память](../semantic-memory.md),
чтобы каждая релевантная запись индексировалась для обоих видов поиска:

```python
import os

from sci_etl_core import AsyncCompositeIngestor
from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)
from sci_etl_core.search import AsyncHybridSearcher, AsyncSearchIndexer, AsyncSqliteFts5Store

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
vector_store = AsyncSqliteEmbeddingStore("memory.db")
text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))

ingestor = AsyncCompositeIngestor(
    AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=vector_store),
    AsyncSearchIndexer(store=text_store),
)


async def show_matches(query: str) -> None:
    searcher = AsyncHybridSearcher(text_store, AsyncSimilarArticleFinder(embedder, vector_store))
    outcome = await searcher.search(query, top_k=10)
    if outcome.degraded:
        print(f"Degraded: {', '.join(outcome.degraded)}")
    for hit in outcome.hits:
        print(f"{hit.score:.4f}  {hit.record_id}  {hit.title}")
```

Добавьте загрузчик в пайплайн из раздела
[Быстрый старт](../../getting-started/quick-start.md):

```python
pipeline = AsyncETLPipeline(
    ...,
    memory_ingestor=ingestor,
    closeables=[client, llm, embedder, vector_store, text_store],
)
```

- **Закрытие хранилищ.** `text_store` помещается в `closeables` по той же
  причине, что и `vector_store`, ведь это одноразовый скрипт: пайплайн владеет
  обоими хранилищами, поэтому `show_matches` должна выполняться внутри
  `async with pipeline`. Долгоживущее приложение вместо этого следует разделу
  [Владение хранилищами](store-ownership.md).
- **Сбои памяти.** `SearchStoreError` при индексировании записывается как
  предупреждение, `Memory ingest failed for <record_id> in AsyncSearchIndexer: ...`,
  в логгер `sci_etl_core.ingest_async`, а чанки записи всё равно получают
  эмбеддинги и её сущности всё равно экспортируются. Сбой эмбеддинга точно так
  же не затрагивает текстовый индекс. `SearchQueryError` не является сбоем
  памяти и приводит к неудаче записи.
- **Порядок загрузчиков.** `AsyncCompositeIngestor` возвращает счётчик своего
  первого загрузчика, поэтому передавайте загрузчик чанков первым;
  `AsyncSearchIndexer` на первом месте вызывает `ValueError`. Без эмбеддингов
  передавайте `AsyncSearchIndexer` прямо в `memory_ingestor=`.
- **Что индексируется.** Один документ на запись, содержащий её заголовок,
  аннотацию, полный текст и `metadata`. Повторная загрузка записи заменяет её
  документ, а запись, у которой пусты и заголовок, и аннотация, и текст,
  удаляется.

## В этом разделе {#in-this-section}

- [Синтаксис запросов](query-syntax.md) — булев язык запросов и его парсер.
- [Ранжированный поиск и фильтрация](ranked-search.md) — `search` против `filter_ids` и сниппеты.
- [Гибридный поиск](hybrid-search.md) — объединение BM25 со сходством эмбеддингов.
- [Фильтры и фасеты](filters-and-facets.md) — фильтры по метаданным и диапазонам, счётчики фасетов и диапазонов.
- [Текстовые хранилища](text-stores.md) — индексы в памяти и SQLite FTS5.
- [Заполнение из векторной памяти](backfill.md) — построение текстового индекса из сохранённых чанков.
- [Графы связанных статей](discovery-graphs.md) — графы связанных статей.
- [Создание пользовательского интерфейса](user-interfaces.md) — модель чтения, которую отображает интерфейс.
- [Владение хранилищами](store-ownership.md) — кто закрывает хранилище и когда.
