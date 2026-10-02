# Eventos de progreso y métricas

Cada ejecución del pipeline recopila métricas y puede informar de su progreso
sobre la marcha.

## Métricas de ejecución {#run-metrics}

`pipeline.last_run_metrics` devuelve un `RunMetrics` de la ejecución más
reciente, terminara como terminara:

```python
from sci_etl_core import AsyncETLPipeline

pipeline = AsyncETLPipeline(..., usage_sources=[llm, embedder])
try:
    await pipeline.run(query="all:galaxy", total_limit=200, newest_first=True)
finally:
    metrics = pipeline.last_run_metrics
    print(
        f"{metrics.outcome}: {metrics.processed} processed, {metrics.irrelevant} irrelevant, "
        f"{metrics.failed} failed in {metrics.duration_seconds:.0f} s"
    )
```

| Campo | Significado |
|-------|-------------|
| `pages`, `listed` | Páginas de listado obtenidas y las entradas que contenían |
| `processed`, `irrelevant`, `deferred`, `failed`, `skipped` | Registros por resultado; los registros `deferred` esperan a la siguiente ejecución por `total_limit` o por un apagado, y los registros `skipped` no tenían identificador |
| `entities_exported` | Entidades entregadas al exportador |
| `memory_faults` | Fallos de ingesta en memoria que se registraron sin hacer fallar su registro |
| `quarantined` | Registros listados que se omitieron porque fallaron `max_attempts` veces en ejecuciones anteriores, cada uno contado una vez por ejecución |
| `listing_truncated` | `True` cuando la fuente detuvo el listado en su límite de resultados |
| `duration_seconds` | Tiempo real de la ejecución |
| `token_usage` | Tokens que consumieron las `usage_sources` durante esta ejecución, o `None` sin fuentes |
| `outcome` | `completed`, `aborted`, `interrupted`, `cancelled` o `failed` |

`usage_sources` acepta cualquier objeto con una propiedad `usage`, como
`AsyncOpenAICompatibleClient`, `AsyncOpenAIEmbedder` o `CachingLLMClient`. Se
resta su consumo previo a la ejecución, de modo que un cliente compartido entre
ejecuciones informa de cada una por separado.

## Eventos de progreso {#progress-events}

Pasa `on_event` para recibir eventos tipados de `sci_etl_core.observability` a
medida que avanza la ejecución:

```python
from sci_etl_core.observability import PageFinished, RecordFinished, RunFinished


def report(event):
    if isinstance(event, RecordFinished) and event.outcome == "failed":
        print(f"{event.record_id} failed after {event.duration_seconds:.1f} s: {event.error!r}")
    elif isinstance(event, PageFinished):
        print(f"page at {event.cursor or 'start'}: {event.metrics.processed} processed so far")
    elif isinstance(event, RunFinished):
        print(f"run {event.metrics.outcome}")


pipeline = AsyncETLPipeline(..., on_event=report)
```

| Evento | Cuándo |
|--------|--------|
| `RunStarted(query, start_index, total_limit, newest_first, cursor)` | Antes de la primera solicitud de listado |
| `PageFetched(offset, entries, new_records, cursor, truncated)` | Llegó una página de listado; los `new_records` aún no se han procesado, y `truncated` marca la página en la que la fuente se detuvo en su límite de resultados |
| `RecordFinished(record_id, title, outcome, duration_seconds, entities, error)` | Un registro salió del pipeline en esta ejecución |
| `PageFinished(offset, duration_seconds, metrics, cursor)` | Terminaron todos los registros de una página; `metrics` es la ejecución hasta ese momento |
| `RunFinished(metrics)` | La ejecución terminó, de la forma que fuera |

`cursor` es el cursor de listado con el que se pidió una página, `None` para la
primera página. `start_index` y `offset` contienen la misma posición como
desplazamiento del listado cuando el extractor pagina por desplazamiento, y
`None` en caso contrario. Cada evento y `RunMetrics` es una dataclass de solo
argumentos con nombre.

El manejador se ejecuta en el bucle de eventos, así que mantenlo rápido: pasa a
una cola el trabajo lento, como una llamada de red. Una excepción que lance se
registra como `Event handler failed: ...` y nunca detiene la ejecución.
`ETLPipeline` acepta los mismos argumentos y también expone
`last_run_metrics`.
