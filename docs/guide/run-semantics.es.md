# Semántica de ejecución

`AsyncETLPipeline.run` ofrece las garantías siguientes. Cada una está numerada
y cada una tiene una prueba en `tests/semantics/test_run_rules.py` cuyo nombre
empieza por el número de la regla, como `test_r1_cursor_waits_for_settled_page`.
Cambiar una regla es un cambio incompatible: cambia la prueba de la regla y
recibe una entrada en [MIGRATION.md](../project/migration.md).

Un registro está **resuelto** (settled) cuando se ha procesado, marcado como
irrelevante u omitido por estar en cuarentena. Un registro es **duradero**
(durable) cuando el exportador conserva sus entidades de forma duradera (R20).
Una página está **atascada** (stalled) cuando en ella fallaron registros y no se
procesó ninguno, o cuando falló el `flush` del exportador para ella. Una página
**termina el listado** cuando no tiene siguiente cursor, no tiene entradas o
está truncada.

| Regla | Garantía | Pruebas | Código |
|-------|----------|---------|--------|
| R1 | El cursor guardado nunca avanza más allá de una página con un registro sin resolver: en cuanto un registro falla, queda aplazado por `total_limit` o se escribe pero no se vuelve duradero por un `flush` fallido, el cursor se queda al principio de esa página durante el resto de la ejecución. Restablecerlo a la primera página (R15, R16) no es avanzar. Un registro omitido por estar en cuarentena cuenta como resuelto (R18). | `test_r1_*` | `_listing_position.py:46-57` |
| R2 | `total_limit` es exacto. Un registro relevante reserva un hueco antes de que se descargue su texto completo, y un registro que falla libera su hueco para otro registro. | `test_r2_*` | `pipeline_async.py:81-98`, `:802-821` |
| R3 | Un registro irrelevante se marca como procesado de inmediato, sin descargar su texto completo. | `test_r3_*` | `pipeline_async.py:805-807` |
| R4 | Una excepción de ingesta en memoria incluida en `MEMORY_FAULTS` se registra y se cuenta en `RunMetrics.memory_faults`, y las entidades del registro se exportan igualmente. | `test_r4_*` | `pipeline_async.py:832-840` |
| R5 | Dos páginas atascadas, sin ninguna página entre ellas que procesara un registro, abortan la ejecución con `PipelineAborted`. Se tolera una sola página atascada. Los registros omitidos por estar procesados o en cuarentena no hacen que una página esté atascada ni que procese. Una página cuyo `flush` del exportador falló está atascada (R21). | `test_r5_*` | `pipeline_async.py:46`, `:562-574` |
| R6 | Una página atascada que termina el listado, o a la que sigue una página que lo termina, aborta la ejecución antes de que se guarde el final. Esto tiene prioridad sobre R15. | `test_r6_*` | `pipeline_async.py:575-576` |
| R7 | Una página sin siguiente cursor, o sin entradas, termina la ejecución como `"completed"` una vez resuelta la página. Un `OffsetListing` guarda entonces el desplazamiento posterior a la última entrada, de modo que la siguiente ejecución encuentra las entradas añadidas después; cualquier otro extractor no guarda cursor, así que la siguiente ejecución empieza desde la primera página. | `test_r7_*` | `_listing_position.py:46-75` |
| R8 | Una página formada solo por registros ya procesados no es el final; la paginación continúa más allá de ella. | `test_r8_*` | `pipeline_async.py:601-613` |
| R9 | Una solicitud de apagado termina los registros en curso, vuelca el exportador, marca los registros que ese volcado hizo duraderos, deja el resto de la página para la siguiente ejecución, mantiene el cursor guardado antes de esa página, cierra el exportador, vuelca el estado y lanza `PipelineInterrupted`. | `test_r9_*` | `pipeline_async.py:515-531`, `:767-785`, `:803-804` |
| R10 | El exportador se vuelca y se cierra, y después se vuelca el estado, termine como termine la ejecución. Un fallo en cualquiera de ellos después de que la ejecución fallara se registra, así que nunca oculta el error original; un fallo al cerrar el exportador después de una ejecución correcta se lanza una vez volcado el estado. | `test_r10_*` | `pipeline_async.py:451-469`, `:698-724` |
| R11 | Un registro cuyo `record_id` falta o está vacío se omite, se registra y se notifica con un evento `RecordFinished` con resultado `"skipped"`. | `test_r11_*` | `pipeline_async.py:740-745` |
| R12 | `sleep_between` se espera entre páginas, nunca después de la página que alcanza `total_limit` o termina el listado. | `test_r12_*` | `pipeline_async.py:582-587` |
| R13 | Una página de listado que no se puede obtener ni analizar aborta la ejecución con `PipelineAborted`, que lleva el número de registros procesados hasta ese momento. | `test_r13_*` | `pipeline_async.py:726-734` |
| R14 | Con un `OffsetListing`, una ejecución con `newest_first=True` pagina desde el desplazamiento 0 hasta encontrar los registros guardados al principio del listado, y después continúa desde el desplazamiento guardado, desplazado hacia abajo según el número de entradas nuevas. Cada cursor de desplazamiento procede de `cursor_for_offset`, y los identificadores listados proceden de los registros de la página, así que cada página se obtiene y analiza una sola vez. | `test_r14_*` | `_listing_position.py:77-134` |
| R15 | Una página truncada que no es una página atascada termina la ejecución como `"completed"`, informa del truncamiento en `RunMetrics.listing_truncated`, en `PageFetched.truncated` y en una línea de registro por ejecución, restablece el cursor guardado a la primera página aunque alguna página no se haya resuelto, y fija `PipelineMetadata.truncated`. La marca la borra la primera ejecución que llega al final del listado sin límite; una ejecución que aborta, se interrumpe o alcanza `total_limit` la deja sin cambios. | `test_r15_*` | `pipeline_async.py:544-548`, `:578-581` |
| R16 | Un `StaleCursorError` reinicia el listado desde la primera página una vez por ejecución; un segundo en la misma ejecución lanza `PipelineAborted`. | `test_r16_*` | `pipeline_async.py:520-529` |
| R17 | `newest_first=True`, o un `start_index` mayor que 0, con un extractor que no es un `OffsetListing` lanza `ValueError` antes de cualquier solicitud. | `test_r17_*` | `pipeline_async.py:443-446` |
| R18 | Con `max_attempts` fijado, los fallos se cuentan mediante `record_failure` solo en las páginas que procesaron un registro, o en las páginas atascadas que una página posterior de la misma ejecución desbloqueó; los fallos retenidos por una página atascada que nunca se desbloquea se descartan. Un registro listado cuyos intentos contados alcanzan `max_attempts` se omite por estar en cuarentena, se cuenta una vez por ejecución en `RunMetrics.quarantined` y se registra una vez. Ningún registro entra en cuarentena en la ejecución en la que falló su último intento. | `test_r18_*` | `pipeline_async.py:124-141`, `:564-567`, `:601-631` |
| R19 | Un registro solo se resuelve cuando hay respuesta. Un fallo de relevancia en un filtro construido con `default_on_error=False`, y una respuesta del LLM que no contiene una lista de entidades, porque la respuesta está vacía o tiene varias claves y ninguna es `result_key`, hacen fallar el registro: queda sin marcar, su intento se cuenta según R18 y se reintenta en la siguiente ejecución. | `test_r19_*` | `llm/openai_compatible_async.py:206-207`, `llm/extraction_async.py:281-288`, `llm/relevance_async.py:96-109`, `pipeline_async.py:802-821` |
| R20 | Un registro se marca como procesado solo cuando sus entidades son duraderas: justo después de `write` en un exportador con `durable_writes = True`, y después del `flush` de la página en los demás casos. Un fallo entre `write` y `flush` repite el registro en la siguiente ejecución y no pierde ninguno. | `test_r20_*` | `pipeline_async.py:767-785`, `:814-817` |
| R21 | Un fallo de `write` hace fallar el registro y cuenta un intento según R18. Un fallo de `flush` deja sin resolver los registros escritos desde el último volcado correcto, no les cuenta ningún intento y convierte la página en atascada, así que dos volcados fallidos seguidos abortan la ejecución según R5. | `test_r21_*` | `pipeline_async.py:773-781`, `:814` |
| R22 | Un fallo en el `open` del exportador aborta la ejecución con `PipelineAborted` antes de cualquier solicitud de listado. | `test_r22_*` | `pipeline_async.py:453-457`, `:704-708` |
| R23 | Todo registro procesado se escribe en el exportador, incluido uno sin entidades; un registro irrelevante no. | `test_r23_*` | `pipeline_async.py:805-814` |

La columna de código cita el código que implementa cada regla. Un cambio que
mueva ese código actualiza aquí su referencia.

## Listados con límite {#capped-listings}

PubMed sirve los primeros 9999 resultados de una consulta, y la búsqueda por
relevancia de Semantic Scholar los primeros 1000. Sus extractores marcan como
truncada la página que alcanza el límite, y se aplica R15: la ejecución
termina y la siguiente vuelve a paginar los resultados accesibles. Los
registros procesados se omiten por identificador, así que la nueva pasada
cuesta solicitudes de listado, no llamadas al LLM: con `page_size=100`, hasta 10
solicitudes para Semantic Scholar y 100 para PubMed. La nueva pasada también
encuentra registros que han entrado en la ventana accesible desde la última
ejecución, lo que importa en un listado ordenado por relevancia. Para evitarla,
acota la consulta, por ejemplo por intervalo de fechas. OpenAlex no tiene
límite: `AsyncOpenAlexExtractor` pagina con los cursores de OpenAlex.
