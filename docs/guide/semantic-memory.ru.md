# Семантическая память

Семантическая память необязательна, и ей нужен extra `embeddings`. Передайте
`memory_ingestor`, чтобы разбивать полный текст каждой релевантной записи на
фрагменты и сохранять их эмбеддинги в векторное хранилище. Затем по этому
хранилищу можно искать по смыслу:

```python
import os

from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
store = AsyncSqliteEmbeddingStore("memory.db")
ingestor = AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=store)


async def show_similar(text: str) -> None:
    finder = AsyncSimilarArticleFinder(embedder, store)
    for record_id, score, metadata in await finder.find_similar_articles(text, top_k=5):
        print(f"{score:.2f}  {record_id}  {metadata['title']}")
```

Добавьте загрузчик в конвейер из раздела [Быстрый старт](../getting-started/quick-start.md)
и перечислите эмбеддер и хранилище среди его `closeables`:

```python
pipeline = AsyncETLPipeline(..., memory_ingestor=ingestor, closeables=[client, embedder, store])
```

- **Что сохраняется.** Загрузка выполняется после проверки релевантности,
  поэтому эмбеддинги получают только релевантные записи. `SlidingWindowChunker`
  по умолчанию использует окна по 350 слов с перекрытием в 50 слов. Повторная
  загрузка записи заменяет все её фрагменты, так что текст, который теперь даёт
  меньше фрагментов, не оставляет устаревших.
- **Сбои.** `EmbeddingError` или `EmbeddingStoreError` во время загрузки
  записываются в журнал, а сущности записи всё равно экспортируются. Сюда
  относятся файл памяти, который не является базой данных SQLite, и эмбеддер,
  вернувший иное число векторов, чем было фрагментов.
- **Хранилища.** `InMemoryEmbeddingStore()` подходит для тестов и
  кратковременных запусков. `AsyncSqliteEmbeddingStore` сохраняет векторы с
  помощью модуля стандартной библиотеки `sqlite3` и при каждом запросе оценивает
  каждый сохранённый вектор. Между запросами он держит векторы в памяти и
  перечитывает их только после записи — из этого хранилища или другого
  процесса, — поэтому расход памяти растёт вместе с хранилищем. Он
  сериализует доступ к своему соединению, так что параллельно обрабатываемые
  записи могут делить одно хранилище, а каждая запись выполняется одной
  транзакцией. Сохранённый вектор, содержащий NaN или бесконечность, никогда не
  попадает в результаты.
- **Собственные хранилища.** Подклассы `AsyncEmbeddingStore` реализуют `add`,
  `delete_record`, `query` и `count`. `replace_record` по умолчанию выполняет
  удаление, а затем добавление; переопределите его, если ваш бэкенд умеет делать
  и то и другое атомарно.
- **Чтение памяти.** `finder.find_best_chunks(text, top_k=5)` ранжирует статьи
  так же, как `find_similar_articles`, но возвращает лучший `SearchHit` каждой
  из них вместе с текстом фрагмента, чтобы показать совпавший отрывок. Метод
  хранилища `iter_records()` выдаёт фрагменты каждой записи в виде
  `StoredRecord`, не загружая векторы.
- **Локальные эмбеддинги.** `AsyncSentenceTransformerEmbedder("all-MiniLM-L6-v2")`
  вычисляет эмбеддинги без сетевых вызовов. Ему нужен extra
  `embeddings-local`, он загружает модель при создании и принимает заранее
  загруженную модель через `model=`.

## Релевантность без LLM {#relevance-without-an-llm}

`AsyncEmbeddingRelevanceFilter` оставляет запись, когда её заголовок и
аннотация достаточно близки к какому-либо эталонному тексту:

```python
from sci_etl_core import AsyncEmbeddingRelevanceFilter

relevance_filter = AsyncEmbeddingRelevanceFilter(
    embedder=embedder,
    reference_texts=["ultra-diffuse galaxies", "low surface brightness galaxies"],
    threshold=0.35,  # минимальное косинусное сходство
)
```

## Поиск ещё и по ключевым словам {#searching-by-keyword-too}

Чтобы индексировать те же записи и для булева поиска, см. раздел
[Локальный поиск и обзор](search/index.md). Его текстовый индекс SQLite,
`AsyncSqliteFts5Store`, — ещё одно хранилище, которое нужно указать в
`closeables` рядом с хранилищем эмбеддингов, а его extra `search` ничего не
устанавливает. Память, заполненную до появления текстового индекса, можно
проиндексировать по сохранённым фрагментам; см.
[Заполнение из векторной памяти](search/backfill.md).
