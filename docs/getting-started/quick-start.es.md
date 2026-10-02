# Inicio rápido

Este ejemplo busca en arXiv, pregunta a un LLM qué artículos son relevantes,
extrae mediciones de su texto completo y las escribe en un CSV con una fila por
medición. Necesita los extras `async`, `arxiv`, `llm` y `pdf`, y lee la clave
de la API de la variable de entorno `LLM_API_KEY`, así que la clave nunca
aparece en el código fuente. Para cargarla desde un archivo `.env`, consulta
[Configuración](configuration.md).

```python
import asyncio
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

RELEVANCE_PROMPT = (
    "Decide whether the paper reports measurements of galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "Extract every measured object from the paper. Reply with JSON: "
    '{"items": [{"name": "...", "value_a": 0.0, "value_b": 0.0}]}.'
)


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(
        api_key=os.environ["LLM_API_KEY"],
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(
            client=client,
            pdf_parser=PdfPlumberParser(),
            latex_parser=LatexTarballParser(),
        ),
        relevance_filter=AsyncLLMRelevanceFilter(
            llm_client=llm, system_prompt=RELEVANCE_PROMPT
        ),
        entity_extractor=AsyncLLMEntityExtractor(
            llm_client=llm, system_prompt=EXTRACTION_PROMPT
        ),
        exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        max_concurrency=4,
        closeables=[client, llm],
    )

    async with pipeline:
        try:
            processed = await pipeline.run("all:galaxy", total_limit=50)
        except PipelineAborted as exc:
            print(f"Stopped early after {exc.partial_count} records: {exc}")
            return
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

## Qué hace una ejecución {#what-a-run-does}

1. Obtiene una página del listado (`page_size` registros, 100 por defecto) en
   el cursor guardado por el gestor de estado (o desde la primera página con
   `start_index=0`) y omite los registros ya procesados. Una página que solo
   contiene registros procesados se salta, no se toma como el final de los
   datos.
2. Para cada registro restante, con un máximo de `max_concurrency` en curso:
   filtro de relevancia → descarga del texto completo → ingesta opcional en
   memoria → extracción de entidades → escritura en el exportador → marcado
   como procesado. Un registro sin entidades también se escribe, para que un
   exportador pueda borrar las filas que una nueva extracción ya no encuentra.
   Los registros irrelevantes se marcan como procesados sin descargar el texto
   completo. Los registros cuyo `record_id` falta o está vacío no se pueden
   seguir, así que se omiten y se registran.
3. Vuelca el exportador, lo que hace duraderas las filas de la página; en un
   exportador con búfer, como `AsyncCsvExporter`, los registros se marcan como
   procesados solo en este momento. Después guarda el cursor del listado y
   repite hasta procesar `total_limit` registros relevantes o hasta que termine
   el listado, esperando `sleep_between` segundos (0 por defecto) antes de cada
   página siguiente. El cursor solo avanza más allá de las páginas cuyos
   registros se resolvieron todos, y un registro que falló en 3 ejecuciones se
   omite por estar en cuarentena; consulta
   [Estado, reanudación y errores](../guide/state.md).

`total_limit` cuenta solo los registros **relevantes**, nunca se supera y por
defecto vale `page_size`. Todos los argumentos de `run()` después de la consulta
son de solo nombre. `max_concurrency` y `page_size` deben ser al menos 1 y
`total_limit` no puede ser negativo; otros valores lanzan `ValueError` antes de
hacer ninguna solicitud. `AsyncArxivExtractor` también espera
`sleep_before_search` segundos (3 por defecto) antes de cada solicitud de
listado, para respetar los límites de frecuencia de arXiv.

Cuando termina la ejecución, de la forma que sea, el exportador se vuelca y se
cierra: `AsyncCsvExporter` escribe `results.csv` en ese momento y mantiene un
`results.csv.journal` durante la ejecución. Al salir, `async with pipeline`
espera `aclose()` en cada elemento de `closeables` que lo tenga: el cliente
HTTP, el cliente del LLM y cualquier `AsyncSqliteStateManager`,
`AsyncSqliteEmbeddingStore` o `AsyncSqliteFts5Store` que uses.

## Los prompts deben pedir JSON {#prompts-must-ask-for-json}

`AsyncOpenAICompatibleClient` solicita el modo JSON
(`response_format={"type": "json_object"}`), y la API de OpenAI rechaza las
solicitudes en modo JSON cuyos mensajes nunca mencionan "JSON". Las formas de
respuesta que lee la biblioteca:

- `AsyncLLMRelevanceFilter` lee la clave `relevant`. Acepta un booleano,
  `0`/`1`, o las cadenas `"true"`, `"false"`, `"yes"`, `"no"`, `"1"` y `"0"`
  en mayúsculas o minúsculas. Cualquier otra cosa, incluida la ausencia de la
  clave, se trata como un error: el registro pasa o, con
  `default_on_error=False`, el filtro lanza `LLMError` y el registro se
  reintenta.
- `AsyncLLMEntityExtractor` lee la lista bajo `result_key` (por defecto
  `"items"`), o el único valor si la respuesta tiene exactamente una clave. La
  lista debe contener objetos; `null` significa que no hay entidades y un
  objeto suelto cuenta como una. Cualquier otro valor ahí lanza `LLMError`, así
  que el registro se reintenta. Una respuesta vacía, y una respuesta con varias
  claves pero sin `result_key`, también lanzan `LLMError`, así que nombra la
  clave en el prompt.
- `AsyncCsvExporter` escribe las claves indicadas en `columns` en sus propias
  columnas y todas las demás en la columna `extra` como JSON, de modo que no se
  pierde ningún valor. Pasa un modelo de Pydantic como `schema=` para que se
  valide cada entidad; consulta [Entidades tipadas](../guide/typed-entities.md).

## Próximos pasos {#next-steps}

- Ejecuta el mismo pipeline desde código síncrono con
  [`ETLPipeline`](blocking-usage.md).
- Carga los ajustes desde YAML y `.env` con la
  [configuración tipada](configuration.md).
- Conserva el artículo y la frase de evidencia detrás de cada valor con las
  [afirmaciones y su procedencia](../guide/claims.md).
- Limpia el CSV y genera gráficos con los
  [pasos de posprocesamiento](../guide/post-processing.md).
