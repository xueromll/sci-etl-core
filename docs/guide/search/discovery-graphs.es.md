# Grafos de descubrimiento

`build_discovery_graph` hace crecer un grafo de artículos relacionados alrededor
de un registro semilla, al estilo de Connected Papers, a partir de fuentes de
aristas que relacionan registros por similitud:

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

- **Fuentes de aristas.** `EmbeddingEdgeSource` relaciona registros cuyo título
  y resumen están próximos en la memoria vectorial, y `MetadataEdgeSource`
  relaciona registros que comparten etiquetas, ponderados por el índice de
  Jaccard de sus conjuntos de etiquetas. Sus claves deben estar entre las
  `facet_keys` del almacén de texto, y por defecto son
  `("categories", "authors")`. Otras nociones de relación se conectan como
  subclases de `AsyncEdgeSource`. Ninguna fuente incluida usa todavía las
  citas, pero `AsyncOpenAlexExtractor` guarda en sus metadatos, bajo
  `references`, los trabajos que cita un artículo.
- **Crecimiento.** El grafo crece `depth` niveles. Cada registro añade hasta
  `fanout` vecinos por fuente cuyo peso sea al menos `min_weight` (0,35 por
  defecto), y `max_nodes` (200 por defecto) se comprueba antes de cada nivel.
  Con `mutual_only` (el valor por defecto), una arista se conserva solo cuando
  cada registro está entre los más cercanos del otro, lo que evita que un
  artículo central se enlace con todo. Solo quedan los registros conectados con
  la semilla.
- **Comunidades.** `GraphNode.community` procede de la propagación de
  etiquetas, que es determinista: el mismo grafo siempre da las mismas
  comunidades. Cuando `max_iterations` (20 por defecto) la interrumpe,
  `DiscoveryGraph.communities_converged` es `False`, y una interfaz debería
  indicar que las comunidades son aproximadas.
- **Solo topología.** Los nodos y las aristas no llevan coordenadas ni
  colores; la interfaz calcula su propia disposición.
- **Filtrado sin E/S.** `filter_graph` es pura y síncrona, así que una interfaz
  puede volver a ejecutarla cada vez que se activa o desactiva una faceta. La
  semilla siempre se mantiene, las aristas que pierden un extremo se descartan
  y las comunidades se conservan para que los colores sean estables. Pasa
  `matched_ids=await text_store.filter_ids(parse_query(...))` para conservar
  solo los registros que coinciden con una consulta; esa llamada acepta la
  negación pura, como `NOT simulation`. `filters` acepta también `RangeFilter`,
  como `RangeFilter("year", low=2020)`.
- **Coste.** `EmbeddingEdgeSource` genera el embedding del título y el resumen
  de cada nodo y lanza como máximo una consulta vectorial por nodo.
  `AsyncSqliteEmbeddingStore` puntúa cada fragmento almacenado en cada consulta,
  pero lee los vectores del disco solo una vez, así que pasa la misma instancia
  del almacén para todo el grafo y mantén `max_nodes` pequeño con una memoria
  grande.
