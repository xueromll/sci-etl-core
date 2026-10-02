# Registro de cambios

Aquí se recogen todos los cambios destacables de sci-etl-core. El formato sigue
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), y las versiones
siguen el [versionado semántico](https://semver.org/). Hasta la 1.0,
una versión menor puede cambiar el comportamiento; cada uno de esos cambios
aparece en **Cambiado**.


## [0.6.0] - 2026-09-27 {#060-2026-09-27}

Esta versión cambia el contrato de datos: los extractores de entidades pueden
devolver entidades tipadas, los exportadores reciben cada registro con sus
entidades, la biblioteca registra mensajes mediante el módulo estándar
`logging` y una instalación base solo necesita Pydantic. Añade afirmaciones con
evidencia y procedencia. Consulta "Actualizar a la 0.6" en MIGRATION.md.

### Añadido {#added}

- **Ciclo de vida del exportador.** `AsyncExporter` tiene `open()`,
  `write(record, entities)`, `flush()` y `aclose()`, y `durable_writes` indica
  si es `write` o `flush` lo que hace duraderas las entidades. El pipeline
  marca un registro como procesado solo cuando sus entidades son duraderas, así
  que un fallo puede repetir un registro pero nunca perderlo.
- `AsyncCsvExporter`, que escribe una fila por entidad con el `record_id` de su
  artículo, guarda todas las demás claves en una columna `extra` y nunca
  fusiona, recorta ni convierte un valor. Genera el archivo una vez por
  ejecución a partir de un diario de solo anexado, de modo que el tiempo de
  exportación crece linealmente con el número de registros. Las celdas que una
  hoja de cálculo ejecutaría como fórmula reciben un apóstrofo inicial; los
  números simples como `-5.361` se escriben sin cambios.
- `AsyncJsonlExporter`, que añade una línea JSON por registro, y
  `read_jsonl_export`, que vuelve a leer la última línea de cada registro.
- **Entidades tipadas.** `AsyncLLMEntityExtractor(schema=Model)` valida cada
  entidad contra un modelo de Pydantic y devuelve instancias del modelo. Pide
  salida estructurada por JSON Schema mediante el nuevo
  `AsyncLLMClient.complete_structured`, que
  `AsyncOpenAICompatibleClient(structured_output=True)` y
  `LLMConfig.structured_output` activan para los endpoints que la admiten.
  `entity_list_schema` construye el esquema solicitado.
- **Motivos de rechazo.** `RecordValidator.validate` devuelve un
  `ValidationResult` de `Violation` que indican el campo y la regla de cada
  rechazo. Los validadores incluidos informan de sus reglas, y
  `CompositeValidator.validate` reúne las infracciones de todos los
  validadores. Los rechazos se registran con sus motivos.
- `AsyncEntityExtractor.extract_record(record, text)` y `requires_record`, para
  los extractores que necesitan el registro. El pipeline llama a
  `extract_record`.
- `AsyncLLMEntityExtractor.prepare` devuelve el texto que se envía al modelo, y
  `stamp` describe el modelo, el prompt, el esquema y la versión de la
  biblioteca que hay detrás de sus entidades. `rejections=` conserva las
  entidades rechazadas en un almacén de rechazos.
- `response_cache_key(schema=, variant=)` y `CachingLLMClient(variant=)`. El
  esquema de una solicitud tipada se incorpora a la clave de caché.
- `sci_etl_core.claims` (provisional): `Claim`, `ClaimDraft`, `EvidenceSpan`,
  `ExtractionStamp`, `locate_quote`, `AsyncLLMClaimExtractor`, los almacenes de
  afirmaciones `InMemoryClaimStore` y `AsyncSqliteClaimStore`,
  `AsyncClaimStoreExporter`, y los almacenes de rechazos
  `InMemoryRejectionStore` y `AsyncSqliteRejectionStore`.
- `DeduplicationStep(source_column=)` añade una columna `sources` que enumera
  las fuentes distintas, como el `record_id` de cada artículo, de todas las
  filas fusionadas en cada fila de salida.
- `ExportError`, `ClaimError` y `ClaimStoreError`.
- Los extras `config`, `arxiv`, `xml`, `html` y `processors`.
- `load_config(load_env=True)` y `load_config_async(load_env=True)`.

### Cambiado {#changed}

- **Incompatible:** los exportadores reciben su destino al construirse e
  implementan `write(record, entities)` en lugar de
  `export(data, destination)`. El pipeline ya no acepta `destination`.
- **Incompatible:** el pipeline escribe en el exportador todo registro
  procesado, incluido uno sin entidades, para que un exportador pueda borrar
  las filas que una nueva extracción ya no encuentra.
- **Incompatible:** el pipeline abre el exportador antes de la primera
  solicitud de listado, lo vuelca después de cada página, y lo vuelca y lo
  cierra antes de volcar el estado, termine como termine la ejecución. Un fallo
  de `open` aborta la ejecución; un fallo de `flush` deja sin resolver los
  registros de la página sin contarles ningún intento.
- **Incompatible:** la instalación base solo requiere `pydantic`. Instala el
  extra `config` para `load_config`, `arxiv` para `AsyncArxivExtractor`, `xml`
  para el extractor de PubMed y los analizadores de JATS y DOCX, `html` para
  `HtmlTextParser`, y `processors` para los procesadores de pandas y los
  sumideros de tablas.
- **Incompatible:** `load_config` y `load_config_async` solo leen un archivo
  `.env` cuando se les pasa `env_path` o `load_env=True`.
- **Incompatible:** cada módulo registra mediante
  `logging.getLogger(__name__)` bajo el logger `sci_etl_core`, en `WARNING` los
  registros fallidos y omitidos, en `ERROR` los fallos de sumideros y de estado,
  y en `INFO` las notas rutinarias. La biblioteca no configura manejadores.
- **Incompatible:** `AsyncEntityExtractor` y `AsyncExporter` son genéricos en
  el tipo de entidad, y todos los argumentos de `AsyncLLMEntityExtractor`
  después de `system_prompt` son de solo nombre.
- `AsyncLLMClient.invalidate` acepta `schema=` para una solicitud tipada.
- El extra `async` ya no instala `aiofiles`, y el extra `sql` ya no instala
  `aiosqlite`.
- `AsyncArxivExtractor` reintenta una respuesta `406` en lugar de hacer fallar
  la solicitud, porque arXiv la devuelve de forma intermitente ante solicitudes
  válidas.

### Eliminado {#removed}

- Las interfaces bloqueantes `Extractor`, `StateManager`, `Exporter`,
  `LLMClient`, `RelevanceFilter` y `EntityExtractor` y las clases
  `Sync*Adapter`.
- `LegacyExtractorAdapter`.
- `AsyncExporter.export` y el argumento `destination` del pipeline.
- `AsyncCsvUpsertExporter`; usa `AsyncCsvExporter`.
- `AsyncSqlTableExporter` y `AsyncPlotly3DExporter`; usa `SqlTableSink` y
  `Plotly3DSink`. `ScatterPlotConfig` se importa desde
  `sci_etl_core.processors`.
- Todos los argumentos `logger=`, `configure_logging` y `AsyncETLPipeline.log`.

## [0.5.1] - 2026-09-26 {#051-2026-09-26}

Esta versión impide que las respuestas del LLM que no contienen respuesta
resuelvan un registro, evita que la caché del LLM las repita y añade límites de
tamaño de descarga y de descompresión. La primera ejecución tras la
actualización falla una vez en la caché del LLM. Consulta "Actualizar a la
0.5.1" en MIGRATION.md.

### Añadido {#added_1}

- `AsyncLLMClient.invalidate(system_prompt, user_content)` notifica una
  respuesta rechazada, y `AsyncLLMResponseCache.delete(key)` elimina una
  entrada; las dos cachés incluidas lo implementan.
- **Límites de tamaño.** `max_download_bytes` en `AsyncArxivExtractor`,
  `AsyncOpenAlexExtractor`, `AsyncPubMedExtractor` y
  `AsyncSemanticScholarExtractor` limita cada cuerpo de respuesta después de
  decodificarlo, y `LatexTarballParser(max_tex_bytes=)` limita el TeX
  descomprimido de un e-print. Una página de listado demasiado grande lanza
  `ExtractionError`; una descarga de texto completo o un e-print demasiado
  grandes se registran y se omiten. Ambos son ilimitados por defecto.
- `AsyncArxivExtractor.from_config(full_text=)` construye el limitador de
  frecuencia del extractor a partir de la sección de configuración `full_text`.
- `AsyncOpenAICompatibleClient` y `CachingLLMClient` exponen `base_url` y
  `temperature`, y todo `AsyncLLMClient` expone `response_format`, que por
  defecto es `{"type": "json_object"}`. `response_cache_key` acepta los tres
  como argumentos con nombre.

### Cambiado {#changed_1}

- Una respuesta vacía del LLM ahora hace fallar el registro en lugar de
  resolverlo. `AsyncOpenAICompatibleClient.complete_json` lanza `LLMError`
  donde antes devolvía `{}`, así que el pipeline reintenta el registro en la
  siguiente ejecución en lugar de marcarlo como procesado sin exportar nada.
- `AsyncLLMEntityExtractor.extract` lanza `LLMError` cuando la respuesta no
  contiene una lista de entidades: está vacía, o tiene varias claves y ninguna
  es `result_key`. Antes devolvía `[]`, y el registro se marcaba como
  procesado.
- `AsyncLLMRelevanceFilter` y `AsyncEmbeddingRelevanceFilter` con
  `default_on_error=False` se cierran ante un fallo: una llamada fallida o un
  veredicto poco claro lanza una excepción, y el registro se reintenta en la
  siguiente ejecución. Antes se interpretaba como irrelevante, y el registro se
  marcaba como procesado para siempre.
- La clave de la caché del LLM incluye ahora el `base_url` del endpoint, la
  temperatura y el formato de respuesta, así que una respuesta guardada para un
  proveedor, una temperatura o un formato ya no se sirve para otro. Las
  respuestas guardadas por versiones anteriores no se encuentran, y la primera
  ejecución tras la actualización llama al LLM para cada solicitud.
- Un `AsyncLLMResponseCache` de terceros sin `delete` sigue sirviendo las
  respuestas que rechaza la biblioteca. Implementa `delete` o acepta la
  repetición.
- `PdfPlumberParser.extract_text` abre un PDF una sola vez para su texto y sus
  tablas, cuando antes lo abría dos veces.
- `AsyncSqliteEmbeddingStore.query` es mucho más rápido cuando se llama
  repetidamente. El almacén mantiene sus vectores en memoria y solo los vuelve a
  leer cuando cambia el archivo, los puntúa con un único producto de NumPy y
  solo lee el texto y los metadatos de los fragmentos devueltos. Un grafo de
  descubrimiento sobre una memoria de 9000 fragmentos se construye unas cuatro
  veces más rápido. El almacén mantiene ahora sus vectores en memoria entre
  consultas hasta que se cierra.
- Las versiones ya no esperan a que sci-etl-cli y udg-catalogue funcionen con
  ellas; en su lugar, la preparación de los consumidores se indica en las notas
  de la versión.

### Corregido {#fixed}

- `AsyncArxivExtractor` reintenta un `408` de tiempo de espera agotado, como
  los demás extractores incluidos. Ahora comparte su código de reintentos, así
  que sus mensajes de reintento y de fallo empiezan por `arXiv` y nombran la
  acción, como `arXiv LaTeX fetch for '2401.00001v1' failed after 3 attempts`.
- `AsyncSqliteFts5Store.search` lanza `SearchQueryError` indicando la versión
  de SQLite cuando SQLite no consigue resaltar un grupo `NEAR` con ámbito de
  campo dentro de `OR` o `NOT`, como hace SQLite 3.50.4 con algunos documentos.
  Antes lanzaba `SearchStoreError` con "database disk image is malformed", lo
  que parece un índice dañado.
- `CachingLLMClient` ya no repite una respuesta que rechazaron el extractor de
  entidades o el filtro de relevancia. La respuesta rechazada se guardaba en
  caché, así que cada reintento obtenía la misma respuesta hasta que el
  registro entraba en cuarentena, sin volver a preguntar al modelo.

## [0.5.0] - 2026-09-25 {#050-2026-09-25}

Esta versión cambia cómo los extractores paginan un listado, qué estado de la
ejecución se guarda y cómo se construye el pipeline. El estado guardado por la
0.4 se actualiza automáticamente. Consulta "Actualizar a la 0.5" en
MIGRATION.md para ver los cambios de código.

### Añadido {#added_2}

- **Paginación por cursor.** Los extractores devuelven un `ListingPage` desde
  `fetch_page`, con el cursor de la página siguiente. Los extractores que
  paginan por desplazamiento implementan también `OffsetListing`, que
  necesitan las ejecuciones `newest_first` y `run(start_index=)`.
- **Cuarentena para los registros que siguen fallando.** `run(max_attempts=3)`
  omite un registro que ha fallado en 3 ejecuciones. `RunMetrics.quarantined`
  cuenta los registros omitidos. Los dos gestores de estado incluidos guardan
  los intentos y el último error de cada registro.
- **Se notifican los límites de resultados.** `RunMetrics.listing_truncated`,
  `PageFetched.truncated` y `PipelineMetadata.truncated` indican cuándo una
  fuente se detuvo en su límite de resultados. Los eventos de progreso incluyen
  también el `cursor` de la página.
- **Sumideros de tablas.** `SqlTableSink` y `Plotly3DSink` en
  `sci_etl_core.processors.sinks` escriben un `DataFrame` posprocesado.
- **Versiones de esquema.** La base de datos de estado SQLite, la caché del LLM,
  el almacén de embeddings y el estado en archivos registran una versión de
  esquema. Un archivo escrito por una versión más reciente se rechaza, con
  `StateStoreError` en el caso de los archivos de estado.
- `StaleCursorError`, para un cursor que la fuente ya no acepta.
- `BaseAppConfig.strict_sections`, para desactivar la validación estricta de la
  configuración.
- `LegacyExtractorAdapter`, que ejecuta un extractor escrito para la 0.4 hasta
  que se traslade. Ya está obsoleto.

### Cambiado {#changed_2}

- **Incompatible:** `AsyncExtractor.fetch_page(query, cursor, page_size)`
  sustituye a `search` y `parse_listing`. Ahora el propio pipeline omite los
  registros procesados.
- **Incompatible:** `PipelineMetadata.cursor` sustituye a `last_start_index`.
- **Incompatible:** los constructores de los pipelines reciben los cinco
  colaboradores por posición o por nombre y todos los demás argumentos por
  nombre. `run()` recibe por nombre todos los argumentos después de `query`.
- **Incompatible:** `RawRecord`, `PipelineMetadata`, `TokenUsage`,
  `RunMetrics` y los eventos de progreso deben construirse con argumentos con
  nombre.
- **Incompatible:** las claves desconocidas en las secciones de configuración
  de la biblioteca, como `search.bm25.titel`, no superan la validación en lugar
  de ignorarse.
- **Incompatible:** se requiere Python 3.11 o posterior.
- Una ejecución que alcanza el límite de resultados de una fuente ahora termina,
  y la siguiente vuelve a empezar desde la primera página en lugar de detenerse
  en el límite.
- Un cursor que la fuente rechaza reinicia una vez el listado desde la primera
  página.
- `AsyncOpenAlexExtractor` pagina con los cursores de OpenAlex y ya no se
  limita a los primeros 10 000 resultados. Ya no admite `newest_first`.
- `AsyncPubMedExtractor` y `AsyncSemanticScholarExtractor` se detienen en la
  última página de resultados sin una solicitud vacía adicional.

### Obsoleto {#deprecated}

Estos nombres siguen funcionando en la 0.5 y se eliminan en la 0.6.0.

Con un sustituto ya disponible (`DeprecationWarning`):

- las interfaces bloqueantes `Extractor`, `StateManager`, `Exporter`,
  `LLMClient`, `RelevanceFilter` y `EntityExtractor` y las clases
  `Sync*Adapter`;
- `LegacyExtractorAdapter`;
- `AsyncSqlTableExporter` y `AsyncPlotly3DExporter`, sustituidos por
  `SqlTableSink` y `Plotly3DSink`.

Con un sustituto que llegará en la 0.6.0 (`PendingDeprecationWarning`, así que
todavía no hay que cambiar nada):

- los argumentos `logger=` y `configure_logging`;
- `AsyncETLPipeline(destination=)`;
- `AsyncExporter.export` y `AsyncCsvUpsertExporter`.

### Eliminado {#removed_1}

- Las claves de configuración `pipeline.max_records` y `pipeline.max_workers`,
  las propiedades correspondientes de `PipelineConfig` y `run(max_records=)`.
  Usa `total_limit` y `max_concurrency`.
- `build_retrying_session`, y `requests` del extra `full`.

### Corregido {#fixed_1}

- `AsyncPubMedExtractor` ya no pide resultados más allá del 9999, que PubMed
  rechaza.

## [0.4.1] - 2026-09-25 {#041-2026-09-25}

### Cambiado {#changed_3}

- `HttpConfig.user_agent` y `build_async_client` usan por defecto
  `sci-etl-core/<installed version>` en lugar de `sci-etl-core/0.1`.

### Corregido {#fixed_2}

- `load_config_async` y `AsyncCsvUpsertExporter` comprueban si un archivo
  existe en un hilo de trabajo en lugar de bloquear el bucle de eventos.
- Los extras `sql` y `full` requieren `sqlalchemy[asyncio]`, así que instalan
  `greenlet`. SQLAlchemy 2.1 ya no lo instala por defecto, y sin él no se podía
  importar `AsyncSqlTableExporter`.

## [0.4.0] - 2026-09-16 {#040-2026-09-16}

### Añadido {#added_3}

- `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor` y
  `AsyncOpenAlexExtractor`. Cada uno rellena `RawRecord.metadata` con
  `authors` y `categories`, y con `published` y `year` cuando la fuente tiene
  fecha, y reintenta ante fallos de transporte, `408`, `429` y errores del
  servidor, respetando `Retry-After`. `AsyncOpenAlexExtractor` guarda además
  bajo `references` los trabajos que cita un artículo.
- `DocxParser` para archivos `.docx` de Word, y `JatsXmlParser` para JATS XML,
  cuyo `parse_article` devuelve un `JatsArticle` con secciones, autores,
  palabras clave, identificadores y referencias.
- Caché de respuestas del LLM: `CachingLLMClient` envuelve cualquier
  `AsyncLLMClient` y responde a las solicitudes repetidas desde un
  `AsyncLLMResponseCache`, ya sea `InMemoryLLMResponseCache` o
  `AsyncSqliteLLMResponseCache`. Un fallo de la caché se registra y se cuenta en
  `CacheStats`, los almacenes lo lanzan como `LLMCacheError`, y nunca hace
  fallar una petición al modelo.
- Apagado ordenado: `AsyncETLPipeline(shutdown=)` y `ETLPipeline(shutdown=)`
  aceptan un `ShutdownSignal`, de modo que SIGINT, SIGTERM o `request()` dejan
  terminar los registros en curso y lanzan `PipelineInterrupted`, una subclase
  de `PipelineAborted`. Ahora toda ejecución termina con el `flush()` del gestor
  de estado, termine como termine.
- Eventos de progreso y métricas de ejecución: `on_event` recibe `RunStarted`,
  `PageFetched`, `RecordFinished`, `PageFinished` y `RunFinished` de
  `sci_etl_core.observability`, y `last_run_metrics` devuelve `RunMetrics` con
  recuentos, duraciones, el resultado de la ejecución y los tokens que
  consumieron las `usage_sources`. `TokenUsage` admite `+` y `-`.
- `run(newest_first=True)` recoge los envíos nuevos en un listado de más
  recientes primero sin volver a recorrer desde el desplazamiento 0.
  `PipelineMetadata` incorpora `head_ids`, `head_offset` y `tail_ids`, que
  guardan los dos backends de estado.
- `rate_limiter` en todos los extractores incluidos,
  `AsyncOpenAICompatibleClient` y `AsyncOpenAIEmbedder`, y `HostRateLimiter`
  para límites por host.
- Componentes construidos a partir de la configuración:
  `AsyncArxivExtractor.from_config`, `AsyncOpenAICompatibleClient.from_config`,
  `AsyncETLPipeline.from_config` y `ETLPipeline.from_config`, además de
  `HttpConfig.build_client()`, `RateLimitConfig.build_limiter()` y
  `PipelineConfig.run_arguments()`. Una sección de configuración `search`
  construye `BM25Weights`, `FusionParams`, `HybridParams` y `GraphParams`.
  `PipelineConfig` incorpora `newest_first`, y `AsyncOpenAICompatibleClient`
  una propiedad `model`.
- `AsyncLLMEntityExtractor(validator=, logger=, label_field=)` descarta y
  registra las entidades que rechaza un `RecordValidator`.
- `ScatterPlotConfig` acepta `hover_data_columns`, `hover_template`,
  `color_continuous_scale`, `color_range`, `color_label`, `marker` y `layout`.
- `ValueClipStep` restringe columnas numéricas durante el posprocesamiento, y
  `TableLayoutStep` ordena las filas y las columnas.
- Consultas de proximidad `NEAR(...)` en el lenguaje de consultas, como el nodo
  `Near` con `NEAR_DISTANCE`, admitidas por los dos almacenes de texto, y
  `QueryChip.near`.
- Filtros de rango: `RangeFilter` conserva los registros cuyas etiquetas están
  entre límites enteros o de texto, como años o fechas ISO 8601, en los dos
  almacenes de texto, en la búsqueda híbrida y en `filter_graph`.
  `AsyncTextSearchStore.range_counts` cuenta las coincidencias en cada uno de
  varios rangos. `SearchFilter` designa cualquiera de los dos tipos de filtro.
- Extractos más completos: `TextHit.snippets` y `FusedHit.snippets` contienen
  un `Snippet` por cada campo con una coincidencia resaltada. `passage_snippet`
  y `snippet_window` construyen extractos de otros textos.
- `backfill_text_index` construye un índice de texto a partir de los fragmentos
  de la memoria vectorial, eliminando las palabras que comparten los fragmentos
  solapados (`merge_passages`), e informa de lo que hizo en un
  `BackfillReport`. `AsyncEmbeddingStore.iter_records` produce los pasajes de
  cada registro como un `StoredRecord` sin cargar los vectores, y lo
  implementan los dos almacenes incluidos.
- `AsyncSimilarArticleFinder.find_best_chunks` devuelve el mejor fragmento de
  cada artículo, con su texto. `SlidingWindowChunker` expone `chunk_words` y
  `overlap_words`.

### Cambiado {#changed_4}

- `PipelineConfig.max_records` es ahora `total_limit`, y `max_workers` es
  `max_concurrency`. Las antiguas claves YAML y los antiguos atributos siguen
  funcionando con un `DeprecationWarning` hasta la 0.5.0, y cargar una
  configuración que asigna valores distintos a una clave antigua y a una nueva
  lanza `ConfigurationError`. `run(max_records=)` queda obsoleto del mismo
  modo.
- `build_retrying_session` queda obsoleto y se eliminará en la 0.5.0, junto
  con `requests` en el extra `full`.
- Un resultado de búsqueda híbrida encontrado solo por la rama semántica lleva
  ahora un extracto de su mejor fragmento en `snippet`, `highlights` y
  `snippets`, que antes estaban vacíos. El código que mostraba el resumen
  siempre que `snippet` estaba vacío debería comprobar `lexical_rank is None`
  en su lugar.
- `ETLPipeline.run` espera al bucle en segundo plano en intervalos cortos, de
  modo que un manejador de señales del hilo que llama se ejecuta enseguida, y
  un `KeyboardInterrupt` cancela la ejecución en el bucle en segundo plano.

## [0.3.0] - 2026-09-15 {#030-2026-09-15}

### Añadido {#added_4}

- Búsqueda booleana local en `sci_etl_core.search`, que solo necesita la
  biblioteca estándar:
  - Un lenguaje de consultas con términos, `"frases"`, términos de prefijo
    `prefix*`, ámbitos `title:`, `abstract:` y `body:`, `AND`, `OR` y `NOT`
    (escritos también como `&&`, `||`, `-` o, en el caso de `AND`, sin nada) y
    paréntesis. `parse_query` devuelve un AST normalizado, y una consulta mal
    formada lanza `SearchQueryError`, cuyos `position` y `token` localizan el
    error. `describe` convierte una consulta en chips para mostrarla.
  - `AsyncSqliteFts5Store`, un índice de texto duradero sobre SQLite FTS5.
    Ordena por BM25 con pesos por campo `BM25Weights`, devuelve extractos en
    texto plano con desplazamientos de resaltado, filtra por metadatos
    (`MetadataFilter`), cuenta facetas sobre sus `facet_keys` y ofrece
    `optimize`, `rebuild_index`, `rebuild_tags` e `integrity_check` para el
    mantenimiento. `fts5_available()` indica si el SQLite del intérprete
    incluye FTS5.
  - `InMemoryTextSearchStore`, que encuentra los mismos registros que el
    almacén FTS5.
  - `AsyncSearchIndexer`, el equivalente de `AsyncChunkIngestor` para el índice
    de texto.
  - Fusión de clasificaciones con `reciprocal_rank_fusion`, la opción por
    defecto, o `normalized_score_fusion`, configurada mediante `FusionParams`.
  - `AsyncHybridSearcher`, que ejecuta una búsqueda léxica, semántica o híbrida
    e informa en `SearchOutcome.degraded` y `SearchOutcome.skipped` de qué ramas
    de recuperación fallaron o no tenían nada que ejecutar.
- Grafos de descubrimiento en `sci_etl_core.search`. `build_discovery_graph`
  hace crecer en anchura la vecindad de un registro semilla a partir de una o
  más fuentes de aristas, conserva por defecto solo los vecinos más cercanos
  mutuos y agrupa los registros en comunidades mediante propagación de
  etiquetas determinista. `GraphParams` limita la profundidad, la ramificación,
  el peso mínimo de las aristas, el número de nodos y las pasadas de
  propagación de etiquetas, y `DiscoveryGraph.communities_converged` indica si
  el límite de pasadas interrumpió la propagación. `filter_graph` reduce un
  grafo ya construido a los registros coincidentes y a filtros de metadatos sin
  ninguna E/S. `label_communities` y `select_edges` también son públicos.
- Fuentes de aristas detrás de una nueva interfaz `AsyncEdgeSource`.
  `EmbeddingEdgeSource` relaciona registros por similitud coseno en la memoria
  vectorial, y `MetadataEdgeSource` por la proporción de etiquetas que dos
  registros tienen en común, como las categorías de arXiv y los autores.
- `sci_etl_core.discovery`, un modelo de lectura para interfaces de usuario:
  `Facet` y `DiscoveryResult`, exportados también desde `sci_etl_core`.
  Importarlo no carga ningún almacén ni ninguna dependencia opcional.
- `AsyncCompositeIngestor`, que envía cada registro a la vez a varios backends
  de memoria, como la memoria vectorial y un índice de texto, de modo que un
  fallo de memoria en uno no detiene a los demás.
- `MemoryIngestor`, el protocolo que cumple un `memory_ingestor`, y
  `MEMORY_FAULTS`, las excepciones que el pipeline trata como fallos de
  memoria.
- `SearchError`, con sus subclases `SearchQueryError` y `SearchStoreError`.
- Un extra `search`. No instala nada, porque la búsqueda solo necesita la
  biblioteca estándar; permite que un archivo de requisitos diga por qué está
  el paquete.

### Cambiado {#changed_5}

- `AsyncETLPipeline(memory_ingestor=)` acepta cualquier `MemoryIngestor`. Un
  `SearchStoreError` durante la ingesta en memoria se registra, y las entidades
  del registro se exportan igualmente, como ante un fallo de embeddings. Un
  `SearchQueryError` no es un fallo de memoria y hace fallar el registro.
- `RawRecord.metadata` ya no está vacío para los registros de arXiv:
  `AsyncArxivExtractor` lo rellena con `categories`, `authors`, `published` y
  `year`. El código que comparaba `metadata == {}` lo notará. Los metadatos de
  los fragmentos que guarda `AsyncChunkIngestor` no cambian.
- `AsyncSqliteEmbeddingStore` funciona sobre un ejecutor interno compartido de
  SQLite. Esto mantiene el comportamiento: los tipos de excepción, los
  mensajes, las transacciones y el comportamiento ante la cancelación no
  cambian.

### Corregido {#fixed_3}

- `AsyncSqliteStateManager`: cancelar una tarea que está esperando una
  operación de estado ya no libera la conexión mientras su hilo de trabajo la
  sigue usando. La siguiente operación espera a que ese hilo termine.

## [0.2.0] - 2026-09-14 {#020-2026-09-14}

### Seguridad {#security}

- `load_config` y `load_config_async` ya no copian el texto de error de
  pydantic en `ConfigurationError`. Ese texto podía incluir los ajustes sin
  procesar y, con ellos, una clave de API leída del entorno. El mensaje
  enumera ahora cada clave errónea y el motivo sin su valor, y el error de
  validación ya no se encadena a él.

### Añadido {#added_5}

- `validate_config(config_cls, raw, source)` valida los ajustes cargados de
  otra forma con los mismos mensajes que no revelan secretos.
- Compatibilidad con `Retry-After`. `AsyncArxivExtractor`,
  `AsyncOpenAICompatibleClient` y `AsyncOpenAIEmbedder` esperan el tiempo que
  pida una respuesta limitada o fallida, mediante `Retry-After` o la cabecera
  `retry-after-ms` que envían las API compatibles con OpenAI, cuando es mayor
  que su espera exponencial. El nuevo argumento `max_retry_after` limita la
  espera (60 segundos por defecto).
- El extractor de arXiv registra cada reintento y cuánto espera.
- Consumo de tokens. `AsyncOpenAICompatibleClient.usage` y
  `AsyncOpenAIEmbedder.usage` devuelven una instantánea `TokenUsage` con
  `requests`, `prompt_tokens`, `completion_tokens` y `total_tokens`. La
  propiedad `usage` de `AsyncLLMClient` y `AsyncEmbedder` devuelve `None` salvo
  que se sobrescriba.
- ruff y mypy se ejecutan en la CI, y un extra `lint` los instala en local.
- Este registro de cambios.

### Cambiado {#changed_6}

- Los reintentos integrados del SDK de OpenAI se desactivan en los clientes de
  chat y de embeddings, así que `max_retries` es ahora el número total de
  intentos. Antes, el SDK podía volver a reintentar por su cuenta cada uno de
  esos intentos.
- Los mensajes de ajustes no válidos empiezan por
  `Invalid configuration in <file>:` y ponen cada problema en su propia línea.
- `AsyncETLPipeline.__aexit__` está anotado para devolver `None`, de modo que
  las herramientas de comprobación de tipos saben que `async with pipeline`
  nunca suprime una excepción.

## [0.1.2] - 2026-09-14 {#012-2026-09-14}

### Corregido {#fixed_4}

- Un `max_concurrency` de 0 dejaba todos los registros esperando para siempre.
  Los valores menores que 1 lanzan ahora `ValueError`, igual que un
  `page_size` menor que 1 y un `total_limit` negativo.
- Un único registro fallido en una página con el resto de registros
  irrelevantes abortaba toda la ejecución. Ahora una ejecución solo aborta
  cuando una segunda página falla sin haber procesado nada antes de cualquier
  progreso, o cuando el listado termina justo después de una página así.
- El pipeline esperaba `sleep_between` una vez más después de alcanzar
  `total_limit`.
- Un `max_retries` menor que 1 hacía que el extractor de arXiv, el cliente del
  LLM y el generador de embeddings fallaran sin un solo intento. Ahora lanza
  `ValueError`.
- `configure_logging` fallaba cuando faltaba la carpeta del archivo de registro
  e ignoraba otro archivo u otro nivel en las llamadas posteriores.
- `AsyncFileStateManager` eliminaba en silencio los espacios de los
  identificadores de registro, así que esos registros se procesaban de nuevo en
  cada ejecución. Ahora los rechaza, y el pipeline omite los identificadores
  vacíos.
- `last_run_at` se registra en UTC con un desplazamiento en lugar de en hora
  local sin zona horaria.

### Añadido {#added_6}

- `PipelineConfig.page_size` y `PipelineConfig.search_delay`.
- Validación de rangos para todas las secciones de configuración.

### Cambiado {#changed_7}

- El flujo de publicación sube los archivos construidos a una versión de GitHub
  que ya existe en lugar de fallar.

## [0.1.1] - 2026-09-14 {#011-2026-09-14}

### Añadido {#added_7}

- Un flujo de publicación que se activa con una etiqueta, ejecuta la batería
  de la CI, comprueba la etiqueta frente a la versión del proyecto y publica en
  PyPI con publicación de confianza.
- Metadatos del paquete para PyPI: licencia, palabras clave, clasificadores y
  URL del proyecto.

## [0.1.0] - 2026-09-13 {#010-2026-09-13}

Primera versión etiquetada: el pipeline asíncrono y su fachada bloqueante, el
extractor de arXiv, clientes de chat y embeddings compatibles con OpenAI,
analizadores de PDF, LaTeX y HTML, exportadores CSV, SQL y Plotly,
procesadores y validadores de dataframes, estado en archivos y en SQLite,
memoria semántica y la guía de migración de udg-catalogue.

[Unreleased]: https://github.com/xueromll/sci-etl-core/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/xueromll/sci-etl-core/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/xueromll/sci-etl-core/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/xueromll/sci-etl-core/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xueromll/sci-etl-core/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xueromll/sci-etl-core/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xueromll/sci-etl-core/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/xueromll/sci-etl-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/xueromll/sci-etl-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xueromll/sci-etl-core/releases/tag/v0.1.0
