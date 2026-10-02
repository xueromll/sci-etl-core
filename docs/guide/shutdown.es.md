# Apagado ordenado

Pasa un `ShutdownSignal` al pipeline y SIGINT (Ctrl+C) o SIGTERM detendrán una
ejecución de forma limpia:

```python
from sci_etl_core import AsyncETLPipeline, PipelineInterrupted
from sci_etl_core.signals import ShutdownSignal

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
    shutdown=ShutdownSignal(),
)

try:
    count = await pipeline.run(query="all:galaxy", total_limit=500)
except PipelineInterrupted as stopped:
    print(f"Stopped after {stopped.partial_count} records; the next run picks up the rest")
```

El pipeline instala los manejadores de señales mientras dura cada `run()` y
después restablece los manejadores anteriores.

- **Primera señal:** no empieza ningún registro nuevo. Los registros ya en
  curso terminan, se vuelca el exportador y los registros que ese volcado hizo
  duraderos se marcan como procesados; los registros que no habían empezado
  quedan sin marcar para la siguiente ejecución. Una solicitud de listado
  pendiente o la espera entre páginas se cancela de inmediato. El cursor
  guardado no avanza más allá de la página interrumpida. Se cierra el
  exportador, se vuelca el estado y `run()` lanza `PipelineInterrupted` con el
  número de registros procesados.
- **Segunda señal:** restablece el manejador anterior y termina de inmediato.
- **Parada programática:** `shutdown.request()` detiene la ejecución del mismo
  modo, por ejemplo desde un manejador web o una prueba.

`PipelineInterrupted` es una subclase de `PipelineAborted`, así que un
`except PipelineAborted` existente la sigue capturando. Captura primero
`PipelineInterrupted` cuando una ejecución interrumpida deba terminar de forma
distinta a una fallida.

## El pipeline síncrono {#the-synchronous-pipeline}

`ETLPipeline` acepta el mismo argumento `shutdown`. Su trabajo se ejecuta en un
bucle de eventos en segundo plano, así que los manejadores se instalan en el
hilo que llama a `run()` y reenvían la solicitud a ese bucle. Llama a `run()`
desde el hilo principal, ya que solo el hilo principal recibe señales:

```python
from sci_etl_core import ETLPipeline
from sci_etl_core.signals import ShutdownSignal

with ETLPipeline(..., shutdown=ShutdownSignal()) as pipeline:
    pipeline.run(query="all:galaxy", total_limit=500)
```

## Volcar el exportador y el estado {#flushing-the-exporter-and-state}

Toda ejecución termina volcando y cerrando el exportador y, después, con el
`flush()` del gestor de estado, sea cual sea su final: completada, abortada,
interrumpida o cancelada. `AsyncCsvExporter` genera su archivo CSV al cerrarse,
y `AsyncSqliteStateManager` consolida su registro de escritura anticipada
(write-ahead log) en `flush()`. Cuando la propia ejecución ha fallado, un fallo
al volcar o cerrar se registra en lugar de lanzarse, para no ocultar el error
original.

## Manejadores propios {#handlers-of-your-own}

`shutdown.guard()` instala los manejadores para un bloque de tu propio código.
Las guardas se anidan, de modo que un pipeline que recibe la misma señal dentro
de ese bloque deja tus manejadores en su sitio cuando termina su ejecución. Los
manejadores solo se instalan desde el hilo principal; en otros hilos `guard()`
registra un mensaje y no instala nada, y `request()` sigue funcionando.
