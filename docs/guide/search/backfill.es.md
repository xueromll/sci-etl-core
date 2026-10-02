# Relleno desde la memoria vectorial

Un despliegue que ha funcionado con memoria semántica pero sin índice de texto
ya guarda el texto completo de cada registro relevante, dividido en
fragmentos, en su `AsyncSqliteEmbeddingStore`. `backfill_text_index` construye
el índice de texto a partir de esos fragmentos, así que no hay que volver a
descargar ni a generar embeddings de nada:

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

Ejecútalo una vez, mientras ningún pipeline esté escribiendo en ninguno de los
dos almacenes, y después añade un `AsyncSearchIndexer` al pipeline como muestra
[Búsqueda y descubrimiento locales](index.md), para que los registros nuevos se
indexen a medida que llegan.

## Fragmentos solapados {#overlapping-chunks}

`SlidingWindowChunker` solapa los fragmentos vecinos, 50 palabras por defecto,
para que ningún pasaje quede cortado en el límite de una ventana. Unir los
fragmentos tal cual repetiría esas palabras, y BM25 contaría dos veces cada
palabra de un límite. El relleno elimina el solapamiento con `merge_passages`,
que descarta las primeras `overlap_words` palabras de cada fragmento cuando
repiten el final del fragmento anterior, de modo que el cuerpo vuelve con cada
palabra una sola vez.

Pasa el `overlap_words` del fragmentador que escribió los fragmentos. Con
`SlidingWindowChunker(chunk_words, overlap_words)`, pasa el mismo
`overlap_words`; si lo omitiste, léelo de un fragmentador construido de la misma
manera, como hace el ejemplo. Un fragmento cuyas primeras palabras no repiten
las últimas del fragmento anterior se conserva entero, así que un valor
incorrecto deja las palabras repetidas en el cuerpo en lugar de recortar texto.

El cuerpo vuelve con un solo espacio entre palabras, tal como lo dividió el
fragmentador; los saltos de línea y la separación entre párrafos desaparecen,
lo que no cambia las coincidencias.

## Qué contiene un documento rellenado {#what-a-backfilled-document-holds}

La memoria vectorial guarda menos de lo que tenía el pipeline, así que por
defecto un documento rellenado tiene:

| Campo | Valor |
|-------|-------|
| `title` | el `title` guardado con los fragmentos del registro |
| `abstract` | vacío, ya que los fragmentos no lo contienen |
| `body` | los fragmentos, fusionados |
| `metadata` | el resto de los metadatos de los fragmentos, como `source_url` |

`AsyncChunkIngestor` no guarda `RawRecord.metadata` con los fragmentos, así que
un documento rellenado no tiene `categories`, `year` ni otras etiquetas de
faceta, y los filtros sobre esas claves no lo encuentran. Si tienes esos
metadatos en otro sitio, como en el CSV exportado, pasa un `build_document` que
los añada. Recibe el `StoredRecord` y el cuerpo fusionado, y devuelve el
`SearchDocument` que se va a indexar, o `None` para dejar fuera el registro:

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

## Registros que ya están en el índice {#records-already-in-the-index}

Un registro que el pipeline ya indexó tiene su resumen y sus metadatos, que a
un documento rellenado le faltan, así que el relleno lo deja como está y lo
cuenta en `skipped_existing`. Pasa `replace_existing=True` para sobrescribir
todos los registros desde la memoria vectorial, por ejemplo después de
reconstruir un índice de texto desde cero. Los registros del índice de texto
que no están en la memoria vectorial nunca se tocan.

- **Lotes.** Los registros se leen y escriben de `batch_size` en `batch_size`
  (100 por defecto), sin cargar ningún vector, así que el uso de memoria se
  mantiene estable en un almacén grande.
- **Otros almacenes vectoriales.** `InMemoryEmbeddingStore` y
  `AsyncSqliteEmbeddingStore` pueden enumerar sus registros con
  `iter_records`. Un `AsyncEmbeddingStore` personalizado que no lo implementa
  lanza `NotImplementedError`.
- **Propiedad.** `backfill_text_index` no cierra ninguno de los dos almacenes;
  ciérralos tú, como hace el ejemplo.
