# Uso bloqueante

`ETLPipeline` es la única clase síncrona. Acepta los mismos argumentos que
`AsyncETLPipeline` —incluidos los mismos colaboradores **asíncronos**— más
`run_timeout`:

```python
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    ETLPipeline,
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

client = build_async_client()
llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
)

with ETLPipeline(
    extractor=AsyncArxivExtractor(
        client=client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
    ),
    relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
    entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
    exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
    closeables=[client, llm],
    run_timeout=3600,
) as pipeline:
    try:
        processed = pipeline.run(query="all:galaxy", total_limit=50)
    except PipelineAborted as exc:
        processed = exc.partial_count

print(f"Processed {processed} relevant records")
```

- **No hay versiones bloqueantes de los componentes individuales.** Para llamar
  a un extractor, un cliente o un exportador directamente desde código síncrono,
  envuelve las llamadas en una corrutina y ejecútala con `asyncio.run`. Para
  conectar código bloqueante a un pipeline, implementa la interfaz asíncrona y
  ejecuta dentro de ella el trabajo bloqueante con `asyncio.to_thread`, igual
  que se llaman los analizadores y procesadores incluidos.
- **`run_timeout`** se expresa en segundos y por defecto no tiene límite.
  Cuando vence, la ejecución se cancela y se lanza `TimeoutError`.
- **Bucle de eventos.** `ETLPipeline` ejecuta el pipeline en un hilo compartido
  en segundo plano con su propio bucle de eventos. Funciona desde scripts
  normales y también cuando se llama desde dentro de un bucle de eventos en
  marcha (por ejemplo, un notebook). Aun así, bloquea el hilo que lo llama
  hasta que termina la ejecución, así que en código asíncrono usa `await` con
  `AsyncETLPipeline`. Una vez que un `ETLPipeline` ha usado un colaborador, ese
  colaborador pertenece al bucle en segundo plano: no lo uses también desde tu
  propio bucle de eventos.
- **`with ETLPipeline(...)`** cierra `closeables` al salir y concede hasta 30
  segundos por recurso.
