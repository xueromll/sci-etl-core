# Búsqueda y descubrimiento locales

Un índice de texto junto a la memoria vectorial añade búsqueda booleana,
búsqueda híbrida que fusiona las clasificaciones por palabras clave y por
significado, facetas de metadatos y grafos de artículos relacionados. Todo ello
está en `sci_etl_core.search` y solo necesita el `sqlite3` de la biblioteca
estándar, así que funciona con un `pip install sci-etl-core` sin extras. El
extra `search` no instala nada; solo permite que un archivo de requisitos diga
por qué está el paquete. Solo la parte semántica necesita el extra
`embeddings`.

## Indexar desde el pipeline {#indexing-from-the-pipeline}

Este ejemplo amplía el de [Memoria semántica](../semantic-memory.md) para que
cada registro relevante se indexe para los dos tipos de búsqueda:

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

Añade el ingestor al pipeline del
[inicio rápido](../../getting-started/quick-start.md):

```python
pipeline = AsyncETLPipeline(
    ...,
    memory_ingestor=ingestor,
    closeables=[client, llm, embedder, vector_store, text_store],
)
```

- **Cerrar los almacenes.** `text_store` va en `closeables` por la misma razón
  que `vector_store`, porque este es un script de un solo uso: el pipeline es
  propietario de ambos almacenes, así que `show_matches` debe ejecutarse dentro
  de `async with pipeline`. Una aplicación de larga duración sigue en cambio
  [Propiedad de los almacenes](store-ownership.md).
- **Fallos de memoria.** Un `SearchStoreError` durante la indexación se
  registra como advertencia,
  `Memory ingest failed for <record_id> in AsyncSearchIndexer: ...`, en el
  logger `sci_etl_core.ingest_async`, y aun así se generan los embeddings de
  los fragmentos del registro y se exportan sus entidades. Del mismo modo, un
  fallo de embeddings no afecta al índice de texto. Un `SearchQueryError` no es
  un fallo de memoria y hace fallar el registro.
- **Orden de los ingestores.** `AsyncCompositeIngestor` devuelve el recuento de
  su primer ingestor, así que pasa primero el ingestor de fragmentos; un
  `AsyncSearchIndexer` en primer lugar lanza `ValueError`. Sin embeddings,
  pasa un `AsyncSearchIndexer` directamente a `memory_ingestor=`.
- **Qué se indexa.** Un documento por registro, con su título, su resumen, su
  texto completo y `metadata`. Volver a ingerir un registro reemplaza su
  documento, y un registro cuyo título, resumen y texto estén todos vacíos se
  elimina.

## En esta sección {#in-this-section}

- [Sintaxis de consultas](query-syntax.md): el lenguaje de consultas booleano y su analizador.
- [Búsqueda por relevancia y filtrado](ranked-search.md): `search` frente a `filter_ids`, y los extractos.
- [Búsqueda híbrida](hybrid-search.md): fusionar BM25 con la similitud de embeddings.
- [Filtros y facetas](filters-and-facets.md): filtros de metadatos y de rango, recuentos de facetas y de rangos.
- [Almacenes de texto](text-stores.md): los índices en memoria y SQLite FTS5.
- [Relleno desde la memoria vectorial](backfill.md): construir el índice de texto a partir de los fragmentos guardados.
- [Grafos de descubrimiento](discovery-graphs.md): grafos de artículos relacionados.
- [Crear una interfaz de usuario](user-interfaces.md): el modelo de lectura que representa una interfaz.
- [Propiedad de los almacenes](store-ownership.md): quién cierra un almacén y cuándo.
