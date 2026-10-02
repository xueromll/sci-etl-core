# Configuración

Los ajustes se cargan desde un archivo YAML y, opcionalmente, desde un archivo
`.env` en modelos de Pydantic. La carga necesita el extra `config`:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
print(config.llm.model, config.pipeline.total_limit)
```

```yaml title="config.yaml"
llm:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  timeout: 120
http:
  user_agent: "my-project/1.0 (mailto:you@example.org)"
  max_retries: 3
  timeout: 25
full_text:
  max_concurrency: 4
pipeline:
  search_query: "all:galaxy"
  total_limit: 100
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_concurrency: 6
  newest_first: true
search:
  bm25: {title: 10, abstract: 4, body: 1}
  fusion: {k: 60}
  hybrid: {candidate_pool: 100, chunk_pool_factor: 5}
  graph: {depth: 2, fanout: 8, min_weight: 0.35}
```

| Sección | Modelo | Campos (valores por defecto) | Construye |
|---------|--------|------------------------------|-----------|
| `llm` | `LLMConfig` | `api_key`, `base_url` (`https://api.openai.com/v1`), `model` (`gpt-4o-mini`), `timeout` (120), `structured_output` (false) | `AsyncOpenAICompatibleClient.from_config` |
| `http` | `HttpConfig` | `user_agent` (`sci-etl-core/<installed version>`), `max_retries` (3), `backoff_factor` (2.0), `timeout` (25) | `build_client()`, `AsyncArxivExtractor.from_config` |
| `full_text` | `RateLimitConfig` | `max_concurrency` (4), `max_rate` (sin fijar), `time_period` (1.0) | `build_limiter()`, `AsyncArxivExtractor.from_config` |
| `pipeline` | `PipelineConfig` | `search_query` (`""`), `total_limit` (100), `page_size` (100), `search_delay` (3.0), `sleep_between` (5.0), `max_concurrency` (6), `newest_first` (false) | `AsyncETLPipeline.from_config`, `run_arguments()`, `AsyncArxivExtractor.from_config` |
| `search` | `SearchConfig` | `bm25`, `fusion`, `hybrid`, `graph`, con los valores por defecto de las dataclasses que construyen | `bm25.to_weights()`, `fusion.to_params()`, `hybrid.to_params()`, `graph.to_params()` |

## Construir componentes a partir de la configuración {#building-components-from-the-config}

Cada sección construye los componentes que configura, o se les pasa. Los
valores que pasas tú tienen prioridad sobre la configuración:

```python
from sci_etl_core import AsyncArxivExtractor, AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

extractor = AsyncArxivExtractor.from_config(
    config.http,
    config.pipeline,
    client=config.http.build_client(),
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    full_text=config.full_text,
)
llm = AsyncOpenAICompatibleClient.from_config(config.llm)
pipeline = AsyncETLPipeline.from_config(
    config.pipeline,
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
)
await pipeline.run(**config.pipeline.run_arguments())
```

`AsyncArxivExtractor.from_config` toma `max_retries` y `backoff_factor` de
`http`, `search_delay` de `pipeline` y su `rate_limiter` de `full_text`. Si
omites `full_text`, el extractor no tiene limitador de frecuencia, así que un
pipeline con `max_concurrency` 6 descarga seis artículos de arxiv.org a la
vez. `AsyncOpenAICompatibleClient` toma `api_key` (el `SecretStr` cargado tal
cual), `base_url`, `model`, `structured_output` y `timeout` como
`default_timeout`. Pon `structured_output: true` solo para un endpoint que
acepte el formato de respuesta `json_schema`, como el de OpenAI; el de DeepSeek
no lo acepta. Ambos aceptan cualquier otro argumento del constructor, como
`rate_limiter`, por nombre. Los extractores de PubMed, Semantic Scholar y
OpenAlex no tienen `from_config`; pasa tú mismo `config.http.max_retries` y
`config.http.backoff_factor` a sus constructores. El pipeline toma
`max_concurrency`, y `run_arguments()` devuelve `query`, `page_size`,
`total_limit`, `sleep_between` y `newest_first` para `run()`; añade
`max_attempts` o `start_index` tú mismo cuando los necesites.
`ETLPipeline.from_config` funciona igual.

La sección search construye las dataclasses de parámetros para la
[búsqueda local](../guide/search/index.md):

```python
from sci_etl_core.search import AsyncHybridSearcher, AsyncSqliteFts5Store

store = AsyncSqliteFts5Store("search.db", weights=config.search.bm25.to_weights())
searcher = AsyncHybridSearcher(
    store,
    finder,
    fusion=config.search.fusion.to_params(),
    params=config.search.hybrid.to_params(),
)
```

## Secciones estrictas {#strict-sections}

Cada sección que define la biblioteca rechaza una clave que no declara, así que
una errata falla de forma visible en lugar de ignorarse. El
`ConfigurationError` nombra la clave:

```text
Invalid configuration in config.yaml:
  search.bm25.titel: Extra inputs are not permitted
```

Las claves `pipeline.max_records` y `pipeline.max_workers`, renombradas en
0.4, se rechazan del mismo modo desde 0.5; usa `total_limit` y
`max_concurrency`. Una aplicación que aún deba cargar un archivo con claves
desconocidas en las secciones de la biblioteca fija `strict_sections = False`
en su clase de configuración. Entonces cada clave desconocida se descarta con
un `UserWarning` que la nombra:

```python
from sci_etl_core import BaseAppConfig


class MyConfig(BaseAppConfig):
    strict_sections = False
```

Las secciones de nivel superior que añade tu aplicación se conservan en ambos
casos, y un tipo de sección que defines tú se valida según indique su propio
`model_config`.

## Detalles {#details}

- **Clave de la API.** La clave procede de la variable de entorno
  `LLM_API_KEY` (elige otra con `api_key_env_var=`). Un archivo `.env` se lee
  en el entorno solo cuando lo pides: pasa su ruta como `env_path`, o pasa
  `load_env=True` para usar el primer `.env` que se encuentre desde el
  directorio de trabajo actual hacia arriba. Sin ninguna de las dos opciones,
  `load_config` nunca lee un archivo `.env`, así que importar y configurar la
  biblioteca no cambia ninguna variable de entorno. La clave se guarda como un
  `SecretStr` de Pydantic, así que no aparece en las representaciones ni en
  los registros. Las variables ya definidas en el entorno tienen prioridad
  sobre `.env`; copia `.env.example` para empezar.
- **El entorno prevalece sobre YAML.** Cuando la variable está definida,
  sustituye a cualquier `llm.api_key` del archivo YAML, que solo se usa como
  respaldo. Aun así, mantén las claves fuera de los archivos de configuración.
- **Ajustes propios del proyecto.** `BaseAppConfig` acepta claves adicionales
  de nivel superior, o puedes heredar de él. Las claves dentro de las secciones
  de la propia biblioteca deben ser las que esas secciones declaran; consulta
  [Secciones estrictas](#strict-sections).
- **Carga asíncrona.** `load_config_async` acepta los mismos argumentos.
- **Errores.** Un archivo YAML que falta o no se puede analizar, un archivo
  cuyo nivel superior no es un mapeo y un fallo de validación lanzan
  `ConfigurationError`. La validación comprueba también los rangos: los
  recuentos como `max_concurrency`, `page_size` y `max_retries` deben ser al
  menos 1, los tiempos de espera y `time_period` deben ser positivos, los
  retardos y `total_limit` no pueden ser negativos, los pesos de BM25 deben ser
  finitos y no negativos, y `graph.min_weight` debe ser finito.
  `fusion.weights` solo se comprueba cuando `fusion.to_params()` construye los
  parámetros, lo que lanza `ValueError` para un peso negativo o no finito. Un
  mensaje de validación muestra cada clave errónea y el motivo en su propia
  línea, pero nunca el valor, así que una clave de API no puede llegar a un
  registro a través de él. `validate_config(config_cls, raw, source)` aplica
  las mismas comprobaciones a ajustes cargados de otra forma.
