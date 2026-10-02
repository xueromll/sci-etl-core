# Limitación de frecuencia

`AsyncETLPipeline(max_concurrency=...)` limita cuántos registros se procesan a
la vez. Para un control más fino, `sci_etl_core.rate_limiter` ofrece
limitadores asíncronos:

- `SemaphoreRateLimiter`: límite de concurrencia
- `AioLimiterRateLimiter`: cubo de tokens; necesita el extra `async`
- `NullRateLimiter`: sin límite

`build_rate_limiter(max_concurrency, max_rate, time_period)` devuelve un cubo
de tokens cuando se fija `max_rate` y un semáforo en caso contrario. Sus
parámetros coinciden con la [sección de configuración](../getting-started/configuration.md)
`full_text`.

## Dar un limitador a un componente {#giving-a-limiter-to-a-component}

Todos los extractores incluidos (`AsyncArxivExtractor`, `AsyncPubMedExtractor`,
`AsyncSemanticScholarExtractor` y `AsyncOpenAlexExtractor`),
`AsyncOpenAICompatibleClient` y `AsyncOpenAIEmbedder` aceptan un
`rate_limiter`. Cada solicitud HTTP, incluidos los reintentos, espera primero
un hueco y lo devuelve cuando llega la respuesta, de modo que ningún hueco
queda ocupado mientras un componente espera para reintentar:

```python
from sci_etl_core import AsyncArxivExtractor
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncArxivExtractor(
    client=client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    rate_limiter=build_rate_limiter(max_rate=1, time_period=3.0),
)
```

## Límites por host {#limits-per-host}

`HostRateLimiter` elige un limitador según el host al que va una solicitud. Un
host cubre también sus subdominios, salvo que un subdominio tenga su propio
limitador, y los hosts sin coincidencia usan `default`, que equivale a no tener
límite si lo omites. El extractor de arXiv llama a dos hosts,
`export.arxiv.org` para los listados y `arxiv.org` para el texto completo, así
que cada uno puede tener su propio presupuesto:

```python
from sci_etl_core.rate_limiter import HostRateLimiter, SemaphoreRateLimiter, build_rate_limiter

arxiv_limits = HostRateLimiter(
    {
        "export.arxiv.org": build_rate_limiter(max_rate=1, time_period=3.0),
        "arxiv.org": SemaphoreRateLimiter(max_concurrency=4),
    }
)
```

## Compartir un límite entre componentes {#sharing-a-limit-between-components}

Pasa el mismo limitador a varios componentes para que compartan un único
presupuesto. Un cliente de chat y un generador de embeddings que llaman al
mismo proveedor consumen la misma cuota:

```python
from sci_etl_core import AsyncOpenAICompatibleClient, AsyncOpenAIEmbedder
from sci_etl_core.rate_limiter import build_rate_limiter

provider_limit = build_rate_limiter(max_rate=50, time_period=60.0)
llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    rate_limiter=provider_limit,
)
embedder = AsyncOpenAIEmbedder(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model="text-embedding-3-small",
    rate_limiter=provider_limit,
)
```

Un `HostRateLimiter` puede compartirse del mismo modo, por ejemplo una
instancia cuyos hosts cubran todos los servicios a los que llama una ejecución.
Los clientes compatibles con OpenAI lo comparan con su `base_url`.
