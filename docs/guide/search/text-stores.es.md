# Almacenes de texto

- **`InMemoryTextSearchStore(facet_keys=...)`** es adecuado para pruebas y
  ejecuciones breves. Encuentra exactamente los mismos registros que el almacén
  SQLite y puntúa con la misma fórmula BM25.
- **`AsyncSqliteFts5Store(path, facet_keys=..., weights=...)`** persiste el
  índice. El texto de cada artículo se guarda una sola vez, cada escritura es
  una transacción y cualquier fallo de SQLite, incluido un archivo que no es una
  base de datos, lanza `SearchStoreError`.
  `weights=BM25Weights(title=10.0, abstract=4.0, body=1.0)` fija cuánto cuenta
  una coincidencia en cada campo; esos son los valores por defecto.
- **FTS5 es obligatorio.** El almacén necesita un Python cuyo SQLite se haya
  compilado con FTS5, y lanza `SearchStoreError` al construirse en caso
  contrario. `fts5_available()` lo comprueba de antemano;
  `InMemoryTextSearchStore` funciona en cualquier entorno.
- **El mantenimiento es explícito.** `optimize()` fusiona los segmentos del
  índice. `integrity_check()` devuelve `False` cuando el índice no concuerda
  con los documentos guardados, por ejemplo después de que otras herramientas
  editaran el archivo, y `rebuild_index()` lo repara a partir del texto
  guardado sin descargar nada. Un archivo creado por una versión más reciente
  de la biblioteca lanza `SearchStoreError` en lugar de usarse.
- **Los almacenes personalizados** heredan de `AsyncTextSearchStore`; consulta
  [Añadir un componente nuevo](../../project/contributing.md#adding-a-new-component).
