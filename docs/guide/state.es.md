# Estado, reanudación y errores

## Backends de estado {#state-backends}

La biblioteca incluye dos backends de estado:

- **`AsyncFileStateManager(processed_ids_file, metadata_file)`** guarda un
  identificador procesado por línea y un archivo de metadatos JSON. Mantiene
  cerrojos de archivo del sistema operativo y escribe los metadatos de forma
  atómica.
- **`AsyncSqliteStateManager(database_path)`** usa una base de datos SQLite en
  modo WAL. Añádelo a `closeables` para que se cierre su conexión. Su `flush()`
  consolida el WAL.

Ambos registran una versión de esquema: la base de datos SQLite en
`PRAGMA user_version` y el archivo de metadatos en una clave
`schema_version`. Cada uno lee los archivos escritos por sci-etl-core 0.4,
cuyo desplazamiento guardado pasa a ser el cursor, y lanza `StateStoreError`
para un archivo escrito por una versión más reciente en lugar de leerlo o
sobrescribirlo. Un `AsyncStateManager` personalizado implementa los cuatro
métodos abstractos; `record_failure`, `failure_counts` y `flush` tienen
implementaciones por defecto.

## Reanudación {#resuming}

Cada ejecución empieza en el `cursor` guardado y omite los identificadores ya
procesados. El cursor se guarda después de cada página, pero solo avanza más
allá de una página cuando todos sus registros están resueltos, es decir,
procesados, marcados como irrelevantes u omitidos por estar en cuarentena.
Cuando un registro falla, o queda pendiente porque se alcanzó `total_limit`, el
cursor se queda al principio de esa página durante el resto de la ejecución,
así que la siguiente ejecución vuelve a ella omitiendo todo lo ya procesado.
Cuando una ejecución llega al final del listado, un extractor que pagina por
desplazamiento guarda el desplazamiento posterior a la última entrada, y
cualquier otro extractor no guarda cursor, así que la siguiente ejecución
empieza desde la primera página. [Semántica de ejecución](run-semantics.md)
enumera todas las reglas que sigue una ejecución, cada una con la prueba que la
comprueba.

Un registro se marca como procesado solo cuando el exportador conserva sus
entidades de forma duradera: justo después de `write` en un exportador con
`durable_writes = True`, y después del `flush` de la página en los demás casos.
Un fallo entre ambos momentos repite el registro en la siguiente ejecución y
nunca lo pierde. Los exportadores incluidos reemplazan la salida anterior de un
registro cuando se vuelve a escribir, así que la repetición es inofensiva; un
exportador propio debe ser idempotente del mismo modo.

`AsyncFileStateManager` lanza `OSError` cuando un archivo de estado existe pero
no se puede leer, en lugar de tratarlo como vacío. Rechaza los identificadores
de registro que contienen un salto de línea o tienen espacios al principio o al
final, ya que ninguno de ellos se volvería a leer sin cambios. Un contenido de
metadatos no válido hace volver a la primera página, lo que solo cuesta una
nueva pasada. Ambos backends registran `last_run_at` como marca de tiempo ISO
8601 en UTC.

## Registros que siguen fallando {#records-that-keep-failing}

Un registro que falla en todas las ejecuciones, como un artículo cuyo PDF hace
fallar al analizador, se reintentaría eternamente y retendría el cursor
guardado en su página. `run(max_attempts=3)`, el valor por defecto, cuenta cada
intento fallido a través del gestor de estado y, a partir de la siguiente
ejecución, omite por estar en cuarentena un registro cuyos intentos alcanzaron
`max_attempts`. Un registro en cuarentena no se procesa ni se reintenta, cuenta
como resuelto para el cursor guardado, se cuenta en `RunMetrics.quarantined` y
se registra una vez por ejecución. Los dos gestores de estado incluidos guardan
los intentos de cada registro y su último error, truncado a 4096 caracteres, y
marcar un registro como procesado los borra.

Los intentos solo se cuentan en las páginas que procesaron un registro, o en
las páginas atascadas que una página posterior de la misma ejecución
desbloqueó. Una página en la que fallan todos los registros no dice nada sobre
ellos: durante una caída del servicio o con una clave de API rechazada, todos
los registros fallan, la ejecución aborta (R5, R6) y no se cuenta ningún
intento.

Esto tiene un límite. Un registro que falla en una página sin ningún otro
registro relevante deja atascada esa página. Si el listado continúa, una página
posterior que procese un registro la desbloquea y el intento se cuenta. Si esa
página es la última del listado, la ejecución aborta y no se cuenta nada, así
que un registro así solo llega a la cuarentena en una ejecución en la que el
listado continúa después de él.

Pasa `max_attempts=None` para no contar nada y reintentar todos los registros
fallidos en cada ejecución, como hacía la 0.4. Un gestor de estado
personalizado que no sobrescribe `record_failure` y `failure_counts` nunca pone
registros en cuarentena.

## Listados de más recientes primero {#newest-first-listings}

El extractor de arXiv lista primero los envíos más recientes, y el extractor de
PubMed ordena de más reciente a más antiguo por defecto, así que los artículos
nuevos empujan a los antiguos hacia desplazamientos mayores. Una ejecución que
se reanuda desde el desplazamiento guardado sigue avanzando hacia atrás por los
artículos más antiguos y nunca ve los nuevos. Pasa `newest_first=True` para
recoger ambos:

```python
await pipeline.run(query="all:galaxy", total_limit=500, newest_first=True)
```

Una ejecución así pagina desde el desplazamiento 0 hasta haber pasado los
registros que la ejecución anterior vio al principio del listado. Lo que se han
desplazado esos registros es el número de envíos nuevos, así que el
desplazamiento guardado ha bajado en ese mismo número. La ejecución salta a la
página justo anterior a ese desplazamiento y comprueba que los registros vistos
allí por última vez siguen en ella. Si es así, los artículos intermedios ya los
resolvieron ejecuciones anteriores y no se vuelven a listar, y la paginación
continúa.

- **Primera ejecución en este modo:** todavía no hay nada guardado que buscar,
  así que recorre desde el desplazamiento 0, omitiendo por identificador los
  registros procesados, y guarda la cabecera del listado para la siguiente
  ejecución.
- **Fallos cerca del principio:** la cabecera que busca la siguiente ejecución
  se toma de la página donde falló un registro, así que esa ejecución pagina al
  menos hasta allí y vuelve a ella.
- **Entradas eliminadas o reordenadas:** cuando los registros anteriores al
  desplazamiento guardado no están donde deberían, la ejecución sigue paginando
  desde el principio en lugar de saltar, y registra
  `Records last seen before the saved offset have moved`.
- **La cabecera guardada ya no aparece en el listado:** la ejecución pagina
  hasta el final del listado, lo que supone una nueva pasada completa, y guarda
  la nueva cabecera.

Una ejecución típica con artículos nuevos cuesta dos o tres solicitudes de
listado al principio, una para comprobar el desplazamiento guardado y las
solicitudes para lo pendiente. Los dos backends de estado guardan los registros
en los que se apoya como `head_ids`, `head_offset` y `tail_ids` en
`PipelineMetadata`. `newest_first` necesita un extractor que pagine por
desplazamiento (`OffsetListing`), y `start_index` no se puede combinar con él.

Sin `newest_first`, pasa `start_index=0` para volver a recorrer un listado desde
su primera página, por ejemplo uno cuyo orden haya cambiado: los registros
procesados se omiten por identificador, así que una nueva pasada cuesta
solicitudes de listado (cada una precedida por la espera `sleep_before_search`
del extractor), pero no vuelve a procesar nada.

## Qué ocurre cuando algo falla {#what-happens-when-something-fails}

| Situación | Comportamiento |
|-----------|----------------|
| La solicitud de listado sigue fallando después de los reintentos | `run()` lanza `PipelineAborted` (causa: `UpstreamError`) |
| La fuente rechaza la solicitud de listado, por ejemplo arXiv responde `400` | `run()` lanza `PipelineAborted` (causa: `ExtractionError`) |
| La carga útil del listado no se puede analizar | `run()` lanza `PipelineAborted` (causa: `MalformedResponseError`) |
| El listado es válido pero no tiene entradas, o una página no tiene siguiente cursor | `run()` devuelve el recuento con normalidad |
| La fuente se detiene en su límite de resultados | `run()` devuelve el recuento con normalidad; la siguiente ejecución empieza desde la primera página |
| La fuente rechaza un cursor guardado (`StaleCursorError`) | el listado se reinicia desde la primera página; un segundo rechazo en la ejecución lanza `PipelineAborted` |
| La página de listado solo contiene registros ya procesados o en cuarentena | la paginación continúa con la página siguiente |
| Un registro lanza una excepción, por ejemplo un fallo transitorio del texto completo | se registra como advertencia; el registro queda sin marcar; el cursor guardado se retiene en su página; se cuenta el intento; los demás registros continúan |
| El `write` del exportador lanza una excepción para un registro | como arriba: el registro falla y se cuenta el intento |
| El `flush` del exportador lanza una excepción | se registra como error; los registros que el volcado habría hecho duraderos quedan sin marcar, no se les cuenta ningún intento y la página cuenta como atascada |
| El `open` del exportador lanza una excepción | `run()` lanza `PipelineAborted` antes de cualquier solicitud de listado |
| Fallan registros de una página y no se procesa ninguno en ella, pero una página posterior procesa un registro | la paginación continúa; los registros fallidos quedan sin marcar para la siguiente ejecución |
| Fallan registros sin que se procese ninguno en una segunda página desde la última página que procesó un registro, o en la última página del listado, por ejemplo por una clave de API rechazada o un CSV ilegible | `run()` lanza `PipelineAborted` (causa: el error del último registro) |
| Se solicita un apagado mediante `shutdown` | `run()` lanza `PipelineInterrupted`; consulta [Apagado ordenado](shutdown.md) |
| arXiv informa de que el LaTeX y el PDF no están disponibles (por ejemplo, 404), o ninguno se puede analizar | el texto completo recurre al resumen |
| arXiv sirve como e-print un único archivo `.tex` comprimido con gzip o un PDF | se lee el TeX, o se usa el PDF en su lugar |
| La llamada al LLM falla dentro de `AsyncLLMRelevanceFilter`, o su veredicto no está claro | devuelve **`True`**; con `default_on_error=False`, `LLMError` se propaga: se registra, el registro queda sin marcar y se reintenta en la siguiente ejecución |
| El registro tiene un resumen vacío | los filtros de relevancia devuelven `default_on_empty_abstract` (**`True`**) |
| La llamada al LLM falla dentro de `AsyncLLMEntityExtractor`, su respuesta está vacía, tiene varias claves y ninguna es `result_key`, o su lista de entidades está mal formada | `LLMError` se propaga: se registra, el registro queda sin marcar y se reintenta en la siguiente ejecución |
| El registro no tiene `record_id` o está vacío | se omite y se registra, ya que no se puede hacer seguimiento como procesado |

## Excepciones {#exceptions}

Todas las excepciones de la biblioteca derivan de `SciEtlError`:
`ExtractionError` (`UpstreamError`, `MalformedResponseError`), `ParsingError`,
`LLMError`, `LLMCacheError`, `EmbeddingError`, `EmbeddingStoreError`,
`SearchError` (`SearchQueryError`, `SearchStoreError`), `StateStoreError`,
`ConfigurationError` y `PipelineAborted` (`PipelineInterrupted`).
`ExtractionError` tiene además `StaleCursorError`. Todas se pueden importar
desde `sci_etl_core`. Los analizadores incluidos lanzan `ParsingError` para los
bytes que no pueden leer; un `Parser` personalizado debería hacer lo mismo, para
que `AsyncArxivExtractor` pase a su siguiente fuente en lugar de hacer fallar el
registro.
