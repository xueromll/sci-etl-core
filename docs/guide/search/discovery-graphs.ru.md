# Графы связанных статей

`build_discovery_graph` выращивает граф связанных статей вокруг исходной
записи, в духе Connected Papers, из источников рёбер, которые связывают записи
по сходству:

```python
from sci_etl_core.search import (
    EmbeddingEdgeSource,
    GraphParams,
    MetadataEdgeSource,
    MetadataFilter,
    build_discovery_graph,
    filter_graph,
)


async def show_neighborhood(record_id: str) -> None:
    sources = [
        EmbeddingEdgeSource(embedder, vector_store, text_store),
        MetadataEdgeSource(text_store, keys=("categories",)),
    ]
    graph = await build_discovery_graph(record_id, sources, text_store, params=GraphParams(depth=2, fanout=8))
    recent = filter_graph(graph, filters=[MetadataFilter("year", {"2025", "2026"})])
    for node in recent.nodes:
        print(f"community {node.community}  links {node.degree}  {node.title}")
```

- **Источники рёбер.** `EmbeddingEdgeSource` связывает записи, заголовок и
  аннотация которых близки в векторной памяти, а `MetadataEdgeSource` — записи
  с общими тегами, с весом, равным индексу Жаккара их наборов тегов. Его ключи
  должны входить в `facet_keys` текстового хранилища, а по умолчанию это
  `("categories", "authors")`. Другие понятия связанности подключаются как
  подклассы `AsyncEdgeSource`. Ни один встроенный источник пока не использует
  цитирования, но `AsyncOpenAlexExtractor` сохраняет работы, которые цитирует
  статья, в своих метаданных под ключом `references`.
- **Рост.** Граф растёт на `depth` уровней. Каждая запись добавляет до
  `fanout` соседей на источник, вес которых не меньше `min_weight` (по
  умолчанию 0,35), а `max_nodes` (по умолчанию 200) проверяется перед каждым
  уровнем. При `mutual_only` (по умолчанию) ребро сохраняется, только когда
  каждая запись входит в число ближайших для другой, что не даёт статье-хабу
  связаться со всем подряд. Остаются только записи, связанные с исходной.
- **Сообщества.** `GraphNode.community` вычисляется распространением меток,
  которое детерминировано: один и тот же граф всегда даёт одни и те же
  сообщества. Когда `max_iterations` (по умолчанию 20) прерывает его раньше,
  `DiscoveryGraph.communities_converged` равен `False`, и интерфейсу следует
  сообщить, что сообщества приблизительны.
- **Только топология.** Узлы и рёбра не несут координат и цветов; интерфейс
  выполняет собственную раскладку.
- **Фильтрация без ввода-вывода.** `filter_graph` — чистая синхронная функция,
  поэтому интерфейс может перезапускать её при каждом переключении фасета.
  Исходная запись остаётся всегда, рёбра, потерявшие конец, удаляются, а
  сообщества сохраняются, чтобы цвета оставались стабильными. Передайте
  `matched_ids=await text_store.filter_ids(parse_query(...))`, чтобы оставить
  только записи, подходящие под запрос; этот вызов принимает и чистое
  отрицание, например `NOT simulation`. `filters` принимает также
  `RangeFilter`, например `RangeFilter("year", low=2020)`.
- **Стоимость.** `EmbeddingEdgeSource` вычисляет эмбеддинг заголовка и
  аннотации каждого узла и выполняет не более одного векторного запроса на
  узел. `AsyncSqliteEmbeddingStore` оценивает каждый сохранённый фрагмент при
  каждом запросе, но читает векторы с диска только один раз, поэтому передавайте
  один и тот же экземпляр хранилища для всего графа и держите `max_nodes`
  небольшим при большой памяти.
