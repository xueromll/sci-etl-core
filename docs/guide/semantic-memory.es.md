# Memoria semántica

La memoria semántica es opcional y necesita el extra `embeddings`. Pasa un
`memory_ingestor` para fragmentar el texto completo de cada registro relevante
y guardar sus embeddings en un almacén vectorial. Después puedes buscar en ese
almacén por significado:

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

Añade el ingestor al pipeline del [inicio rápido](../getting-started/quick-start.md)
e incluye el generador de embeddings y el almacén entre sus `closeables`:

```python
pipeline = AsyncETLPipeline(..., memory_ingestor=ingestor, closeables=[client, embedder, store])
```

- **Qué se guarda.** La ingesta se ejecuta después del filtro de relevancia,
  así que solo se generan embeddings de los registros relevantes.
  `SlidingWindowChunker` usa por defecto ventanas de 350 palabras con un
  solapamiento de 50. Volver a ingerir un registro reemplaza todos sus
  fragmentos, de modo que un texto que ahora produce menos pasajes no deja nada
  obsoleto.
- **Fallos.** Un `EmbeddingError` o un `EmbeddingStoreError` durante la
  ingesta se registra, y las entidades del registro se exportan igualmente.
  Eso incluye un archivo de memoria que no es una base de datos SQLite y un
  generador de embeddings que devuelve un número de vectores distinto al de
  pasajes.
- **Almacenes.** `InMemoryEmbeddingStore()` es adecuado para pruebas y
  ejecuciones breves. `AsyncSqliteEmbeddingStore` persiste los vectores con el
  módulo `sqlite3` de la biblioteca estándar y puntúa cada vector almacenado en
  cada consulta. Mantiene los vectores en memoria entre consultas y solo los
  vuelve a leer después de una escritura, de este almacén o de otro proceso,
  así que el uso de memoria crece con el almacén. Serializa el acceso a su
  conexión, de modo que los registros concurrentes pueden compartir un
  almacén, y cada escritura es una sola transacción. Un vector almacenado que
  contenga NaN o infinito nunca aparece en los resultados.
- **Almacenes personalizados.** Las subclases de `AsyncEmbeddingStore`
  implementan `add`, `delete_record`, `query` y `count`. `replace_record`
  borra y luego añade por defecto; sobrescríbelo si tu backend puede hacer
  ambas cosas de forma atómica.
- **Leer la memoria.** `finder.find_best_chunks(text, top_k=5)` clasifica los
  artículos igual que `find_similar_articles`, pero devuelve el mejor
  `SearchHit` de cada uno, con el texto del fragmento incluido, para mostrar el
  pasaje que coincidió. El método `iter_records()` de un almacén produce los
  pasajes de cada registro como `StoredRecord`, sin cargar los vectores.
- **Embeddings locales.** `AsyncSentenceTransformerEmbedder("all-MiniLM-L6-v2")`
  genera embeddings sin llamadas de red. Necesita el extra `embeddings-local`,
  carga el modelo al construirse y acepta un modelo ya cargado con `model=`.

## Relevancia sin un LLM {#relevance-without-an-llm}

`AsyncEmbeddingRelevanceFilter` conserva un registro cuando su título y su
resumen están lo bastante cerca de algún texto de referencia:

```python
from sci_etl_core import AsyncEmbeddingRelevanceFilter

relevance_filter = AsyncEmbeddingRelevanceFilter(
    embedder=embedder,
    reference_texts=["ultra-diffuse galaxies", "low surface brightness galaxies"],
    threshold=0.35,  # similitud coseno mínima
)
```

## Buscar también por palabras clave {#searching-by-keyword-too}

Para indexar los mismos registros también para la búsqueda booleana, consulta
[Búsqueda y descubrimiento locales](search/index.md). Su índice de texto SQLite,
`AsyncSqliteFts5Store`, es un almacén más que hay que incluir en `closeables`
junto al almacén de embeddings, y su extra `search` no instala nada. Una
memoria llenada antes de añadir el índice de texto puede indexarse a partir de
sus fragmentos guardados; consulta
[Relleno desde la memoria vectorial](search/backfill.md).
