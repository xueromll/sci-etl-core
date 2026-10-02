# Registro

Cada módulo de sci-etl-core registra mensajes mediante el módulo estándar
`logging`, con un logger que lleva el nombre del módulo, como
`sci_etl_core.pipeline_async` o `sci_etl_core.extractors.arxiv_async`. Todos
cuelgan del logger `sci_etl_core`. La biblioteca no instala manejadores ni fija
niveles, así que no se imprime nada hasta que la aplicación configura el
registro:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
logging.getLogger("sci_etl_core.extractors").setLevel(logging.WARNING)
```

Los niveles significan:

| Nivel | Se usa para |
|-------|-------------|
| `ERROR` | Un fallo de un sumidero o almacén que la ejecución notifica: falló `flush` o `aclose` de un exportador, no se pudo volcar el estado, no se pudo cerrar un recurso, un manejador de eventos lanzó una excepción |
| `WARNING` | Algo que cambia lo que la ejecución produce o cuesta: un registro falló o se omitió, un registro se puso en cuarentena, una fuente se detuvo en su límite de resultados o rechazó un cursor, falló un backend de memoria, una descarga no era utilizable, un reintento, una señal de apagado |
| `INFO` | Notas rutinarias: la validación rechazó una entidad o una afirmación, el punto donde se reanudó una ejecución `newest_first` |

Los mensajes conservan la redacción que las versiones anteriores pasaban a los
invocables `logger=`, como `Record processing failed: LLMError('...')`, de modo
que un filtro o una alerta escritos para ellos siguen coincidiendo.

Los eventos de progreso de [Observabilidad](observability.md) siguen siendo el
canal estructurado: cuenta registros, páginas y resultados a partir de los
eventos, y usa los registros para conocer los motivos.
