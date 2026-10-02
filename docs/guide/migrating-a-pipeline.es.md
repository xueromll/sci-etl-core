# Migrar un pipeline

Esta guía traslada un pipeline de investigación existente a `sci-etl-core`,
usando como ejemplo práctico una migración real:
[udg-catalogue](https://github.com/xueromll/udg-catalogue), que construye con
un LLM un catálogo de galaxias ultradifusas (UDG) a partir de artículos de
arXiv.

Cada fragmento "antes" procede de udg-catalogue tal como era antes de la
migración. Cada fragmento "después" de los pasos 1 a 9 procede del proyecto
migrado sobre sci-etl-core 0.2, en el
[commit `8cd9471`](https://github.com/xueromll/udg-catalogue/tree/8cd94711b864212a8fa0d55d60f51e500cf42ec3).
Algunas de esas llamadas de la 0.2 se han renombrado o eliminado desde
entonces. [Adónde llegarás](#where-youll-end-up) muestra el proyecto en la 0.6,
y [Actualizar el proyecto](#upgrading-the-project) muestra cómo cambió el
código en la [rama `main`](https://github.com/xueromll/udg-catalogue/tree/main)
del proyecto al pasar a la 0.4, la 0.5 y la 0.6. La
[guía de migración](../project/migration.md) enumera todos los cambios por
versión. La ciencia es astronomía, pero nada en los pasos depende de ella:
sustituye los prompts, los campos y las reglas del dominio por los tuyos.

- [El proyecto antes](#the-project-before)
- [Adónde llegarás](#where-youll-end-up)
- [Relaciona tu pipeline con la biblioteca](#map-your-pipeline-onto-the-library)
- [Paso 1: instala y enlaza la biblioteca](#step-1-install-and-link-the-library)
- [Paso 2: configuración y secretos](#step-2-configuration-and-secrets)
- [Paso 3: fuente y texto completo](#step-3-source-and-full-text)
- [Paso 4: los pasos con el LLM](#step-4-the-llm-steps)
- [Paso 5: reglas del dominio como complementos](#step-5-domain-rules-as-plug-ins)
- [Paso 6: exportación y estado](#step-6-export-and-state)
- [Paso 7: posprocesamiento](#step-7-post-processing)
- [Paso 8: comprueba la paridad antes de cambiar el comportamiento](#step-8-check-parity-before-changing-behavior)
- [Paso 9: borra el código antiguo](#step-9-delete-the-old-code)
- [Actualizar el proyecto](#upgrading-the-project)
- [Lo que reveló la migración](#what-the-migration-uncovered)
- [Adaptarlo a tu campo](#adapting-this-to-your-field)

---

## El proyecto antes {#the-project-before}

udg-catalogue busca en arXiv `cat:astro-ph.GA AND abs:ultra-diffuse`. Para cada
artículo pregunta a un LLM si el resumen informa de observaciones reales,
descarga la fuente LaTeX o el PDF, pide al LLM que extraiga cada galaxia como
JSON y fusiona las galaxias en un CSV. Después, un paso de posprocesamiento
elimina duplicados, puntúa la completitud, asigna constelaciones y grupos 3D, y
escribe el catálogo ordenado que hay detrás de un panel de Streamlit.

La maquinaria ETL vivía en módulos planos en la raíz del proyecto:

| Módulo | Líneas | Responsabilidad |
|--------|--------|-----------------|
| `arxiv_client.py` | 198 | búsqueda en arXiv y análisis de Atom, descarga de LaTeX y PDF, extracción de tablas, recorte de referencias, las dos llamadas al LLM |
| `data_processor.py` | 314 | archivo de identificadores procesados, validación de galaxias, upsert en CSV, deduplicación, completitud, constelaciones, agrupamiento, indicadores de calidad |
| `main.py` | 94 | bucle de paginación sobre un `ThreadPoolExecutor` |
| `config.py`, `logger.py`, `incremental.py` | 97 | YAML leído en constantes de módulo, configuración del registro, desplazamiento para reanudar |

El bucle de orquestación de `main.py` era así:

```python
while papers_processed < MAX_PAPERS:
    xml_data = search_arxiv(SEARCH_QUERY, max_results=MAX_PAPERS, start_index=start_index)
    if not xml_data:
        break
    papers, total_in_xml = parse_arxiv_xml(xml_data, processed_ids)
    if total_in_xml == 0 or not papers:
        break

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_paper_task, paper, processed_ids): paper for paper in papers}
        for future in as_completed(futures):
            try:
                success = future.result()
                if success:
                    papers_processed += 1
                if papers_processed >= MAX_PAPERS:
                    break
            except Exception as exc:
                logger.error(f"Paper processing generated an exception: {exc}")

    start_index += MAX_PAPERS
    save_pipeline_metadata(start_index)
    time.sleep(SLEEP_BETWEEN)
```

## Adónde llegarás {#where-youll-end-up}

Después de la migración, toda la parte de ingesta son unas pocas funciones que
conectan componentes de la biblioteca. Este es `udg_catalogue/pipeline.py`
sobre sci-etl-core 0.6, reducido al pipeline de ingesta y sin los envoltorios
que registran el progreso:

```python
def build_catalogue_exporter(config: CatalogueConfig) -> AsyncCsvExporter:
    return AsyncCsvExporter(config.paths.raw_catalogue, [KEY_COLUMN, *MEASUREMENT_FIELDS])


def build_entity_extractor(
    config: CatalogueConfig,
    llm_client: AsyncLLMClient,
    rejections: AsyncRejectionStore | None = None,
) -> AsyncLLMEntityExtractor[dict[str, Any]]:
    return AsyncLLMEntityExtractor(
        llm_client,
        EXTRACTION_PROMPT,
        result_key=EXTRACTION_RESULT_KEY,
        timeout=config.llm.timeout,
        validator=build_galaxy_validator(),
        rejections=rejections,
        label_field=KEY_COLUMN,
    )


def build_pipeline(config, logger, http_client, llm_client, library, shutdown=None):
    cache = AsyncSqliteLLMResponseCache(config.paths.llm_cache)
    cached_llm = CachingLLMClient(llm_client, cache, model=config.llm.model)
    rejections = AsyncSqliteRejectionStore(config.paths.rejections)
    extractor = AsyncArxivExtractor.from_config(
        config.http,
        config.pipeline,
        client=http_client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        full_text=config.full_text,
    )
    return AsyncETLPipeline.from_config(
        config.pipeline,
        extractor=extractor,
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=cached_llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=build_entity_extractor(config, cached_llm, rejections),
        exporter=build_catalogue_exporter(config),
        state_manager=AsyncFileStateManager(config.paths.processed_ids, config.paths.pipeline_metadata),
        closeables=[http_client, llm_client, cache, rejections, *library.closeables],
        memory_ingestor=library.memory_ingestor(build_chunker(config.embeddings)),
        shutdown=shutdown,
        on_event=PipelineEventLogger(logger.info, logger.warning),
        usage_sources=[llm_client, *library.usage_sources],
    )


async def run_ingestion(config, logger, start_index=None, shutdown=None) -> int:
    library = open_paper_library(config)
    http_client = build_http_client(config)
    llm_client = build_llm_client(config)
    async with build_pipeline(config, logger, http_client, llm_client, library, shutdown) as pipeline:
        return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

`build_pipeline` recibe los clientes HTTP y del LLM como argumentos, así que
las pruebas del proyecto pasan un `httpx.MockTransport` que sirve un feed Atom
y un e-print falsos, además de un `AsyncLLMClient` con respuestas preparadas, y
ejecutan el pipeline real sin conexión.

`main.py` se reduce a cargar la configuración, ejecutar la ingesta y construir
los resultados:

```python
config = load_catalogue_config(arguments.config)
log = configure_run_logging(config.paths.log_file)
processed = asyncio.run(run_ingestion(config, log, start_index, ShutdownSignal()))
catalogue = build_sorted_catalogue(config, log.info, replace=arguments.replace_catalogue)
write_manifest(config, log.info)
```

Lo que se queda en el proyecto es la parte que solo puede escribir un
astrónomo: los prompts, las reglas para nombrar y validar galaxias, la
correspondencia por posición en el cielo, las características usadas para el
agrupamiento y el panel de control.

## Relaciona tu pipeline con la biblioteca {#map-your-pipeline-onto-the-library}

Empieza por clasificar cada función del pipeline antiguo en uno de tres
grupos: sustituida por un componente de la biblioteca, sustituida por un
componente de la biblioteca más un pequeño complemento, o conservada.

| Antes (udg-catalogue) | Después | Lo que sigues escribiendo tú |
|-----------------------|---------|------------------------------|
| `search_arxiv`, `parse_arxiv_xml` | `AsyncArxivExtractor` | nada |
| `fetch_paper_text`, `extract_tables_from_pdf`, `trim_references` | `AsyncArxivExtractor` con `LatexTarballParser` y `PdfPlumberParser` | nada |
| sesión de `requests` con `Retry` | `build_async_client` | nada |
| `is_paper_relevant` | `AsyncLLMRelevanceFilter` | el prompt |
| `extract_udg_data` | `AsyncLLMEntityExtractor(result_key="galaxies")` | el prompt |
| cliente de OpenAI apuntado a DeepSeek | `AsyncOpenAICompatibleClient` | la URL base y el modelo |
| `upsert_to_csv` | `AsyncCsvExporter` y después `DeduplicationStep` en el posprocesamiento | la lista de columnas |
| `load_processed_ids`, `save_processed_id`, `incremental.py` | `AsyncFileStateManager` | las rutas de los archivos |
| bucle de `main.py` | `AsyncETLPipeline` | la conexión mostrada arriba |
| `logger.py` | el módulo estándar `logging` | los manejadores del registro de la ejecución |
| `config.py` | subclase de `BaseAppConfig` y `load_config` | los ajustes del proyecto |
| `universal_normalize_name` | subclase de `KeyNormalizer` | las reglas de correspondencia de nombres |
| `is_valid_galaxy` | `RecordValidator` pasados a `AsyncLLMEntityExtractor(validator=)` | las reglas de los campos |
| `clean_duplicates` | `NormalizationStep` y `DeduplicationStep` | un `NeighborMatcher` para posiciones en el cielo |
| `calculate_completeness`, `assign_quality_flag` | `CompletenessStep`, `QualityFlagStep` | la lista de campos |
| `assign_3d_clusters` | `ClusteringStep` | un `FeatureExtractor` para posiciones 3D |
| `assign_constellations`, gráficos, panel | se conservan | código del dominio, como `Processor` cuando encaja |

La tabla nombra los componentes de sci-etl-core 0.6. Los pasos 1 a 9 muestran
los componentes de la 0.2 que udg-catalogue usaba entonces, como un exportador
CSV con upsert y un envoltorio de extractor con validación, que versiones
posteriores sustituyeron.

## Paso 1: instala y enlaza la biblioteca {#step-1-install-and-link-the-library}

Durante la migración cambiarás las dos bases de código, así que instala la
biblioteca en modo editable en el entorno del proyecto. udg-catalogue está a
dos carpetas de distancia de su clon de sci-etl-core:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "../../sci-etl-core[async,llm,pdf,cluster]"
python -c "import sci_etl_core; print(sci_etl_core.__file__)"
```

En Windows, activa el entorno con `.venv\Scripts\activate`. El último comando
debería imprimir una ruta dentro de la carpeta `src` del clon. Elige los
extras de los componentes que uses: udg-catalogue necesita `async` para el
extractor de arXiv y el exportador CSV, `llm` para el cliente compatible con
OpenAI, `pdf` para `PdfPlumberParser` y `cluster` para `ClusteringStep`.

Una instalación editable registra la ruta absoluta del clon. Si mueves o
renombras la carpeta de la biblioteca, `import sci_etl_core` falla hasta que la
reinstales; eso es exactamente lo que pasó cuando el espacio de trabajo de
udg-catalogue se trasladó a una carpeta sincronizada de OneDrive.

Los entornos desplegados no ven un clon vecino, y pip no puede instalar un
mismo paquete desde dos orígenes en una misma resolución. Por eso
udg-catalogue mantiene sus paquetes de terceros fijados en
`requirements-app.txt` y elige el origen de la biblioteca en dos archivos
mínimos. Para el desarrollo local, `requirements-local.txt`:

```text
-r requirements-app.txt
-e ../../sci-etl-core[async,llm,pdf,cluster]
```

Para Docker, la CI y los usuarios nuevos, `requirements.txt` instala la versión
publicada en PyPI:

```text
-r requirements-app.txt
sci-etl-core[async,llm,pdf,cluster]>=0.2.0,<0.3
```

Fija un intervalo de versiones en lugar de una versión exacta, para que las
versiones de corrección lleguen sin cambiar el proyecto, y sube el límite
superior de forma deliberada después de comprobar una nueva versión menor con
tus pruebas. Antes de que la biblioteca estuviera en PyPI, udg-catalogue
incluía en el repositorio un wheel construido con
`pip wheel --no-deps -w vendor path/to/sci-etl-core` y lo instalaba desde
`vendor/`; eso sigue funcionando para una compilación que no puede acceder a
PyPI.

## Paso 2: configuración y secretos {#step-2-configuration-and-secrets}

**Antes** (`config.py`): el YAML se leía en constantes de módulo al importar el
módulo.

```python
load_dotenv()
API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg: dict = yaml.safe_load(f)

MODEL: str = cfg.get("model", "deepseek-v4-flash")
CSV_FILE: str = os.path.join(SCRIPT_DIR, cfg.get("csv_file", "udg_database.csv"))
MAX_PAPERS: int = cfg.get("max_papers", 500)
```

**Después**: `config.yaml` usa las secciones de la biblioteca (`llm`, `http`,
`pipeline`) más las propias del proyecto (`paths`, `clustering`,
`deduplication`):

```yaml
llm:
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  timeout: 120

http:
  user_agent: "UDG-ResearchScript/1.0 (lanhua1122333@gmail.com)"
  max_retries: 4
  backoff_factor: 5.0
  timeout: 25

pipeline:
  search_query: "cat:astro-ph.GA AND abs:ultra-diffuse"
  max_records: 500
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_workers: 6

paths:
  raw_catalogue: "udg_database.csv"
  sorted_catalogue: "udg_database_sorted.csv"
  processed_ids: "processed_arxiv_ids.txt"
  pipeline_metadata: "pipeline_meta.json"

clustering:
  max_distance_mpc: 5.0
  min_samples: 2

deduplication:
  max_separation_arcsec: 3.0
```

`udg_catalogue/config.py` hereda de los modelos de la biblioteca:

```python
class CataloguePipelineConfig(PipelineConfig):
    page_size: int = 100
    search_delay: float = 3.0


class CatalogueConfig(BaseAppConfig):
    pipeline: CataloguePipelineConfig = Field(default_factory=CataloguePipelineConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    deduplication: DeduplicationConfig = Field(default_factory=DeduplicationConfig)


def load_catalogue_config(config_path: Path = DEFAULT_CONFIG_PATH) -> CatalogueConfig:
    resolved = Path(config_path).resolve()
    config = load_config(
        CatalogueConfig,
        resolved,
        resolved.parent / ".env",
        api_key_env_var=API_KEY_ENV_VAR,
    )
    return config.model_copy(update={"paths": config.paths.anchored_at(resolved.parent)})
```

Merece la pena copiar tres decisiones:

- **Conserva el nombre de tu secreto.** `api_key_env_var="DEEPSEEK_API_KEY"`
  hace que el archivo `.env` existente y el archivo de Docker Compose sigan
  funcionando sin cambios. La clave se guarda como `SecretStr`, así que nunca
  aparece en las representaciones ni en los registros.
- **Amplía las secciones heredando.** `CataloguePipelineConfig` añade
  `page_size` y `search_delay` y conserva todos los campos que lee la
  biblioteca.
- **Resuelve las rutas a partir del archivo de configuración.** Pasar de forma
  explícita el `.env` que está junto a la configuración y anclar las rutas
  relativas a la carpeta de la configuración hace que el pipeline se comporte
  igual sea cual sea el directorio desde el que lo inicies. El código antiguo
  resolvía la mayoría de las rutas desde la carpeta del script, pero
  `pipeline_meta.json` y `analysis/` desde el directorio de trabajo.

Los valores de la configuración no se aplican automáticamente: pásalos a los
constructores y a `run()`, como hace `build_pipeline`.

## Paso 3: fuente y texto completo {#step-3-source-and-full-text}

**Antes** (`arxiv_client.py`, recortado):

```python
def search_arxiv(query: str, max_results: int = 5, start_index: int = 0) -> bytes | None:
    ...
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(base_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=(10, 60))
            if response.status_code == 429:
                time.sleep(20)
                continue
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(5 * (attempt + 1))
            else:
                logger.error(f"arXiv search failed after {MAX_RETRIES} attempts: {e}")
    return None


def fetch_paper_text(entry: dict) -> str:
    ...
    with session.get(source_url, headers={"User-Agent": USER_AGENT}, timeout=25, verify=False, stream=True) as r:
        ...
```

**Después**:

```python
extractor = AsyncArxivExtractor(
    client=http_client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    max_retries=config.http.max_retries,
    backoff_factor=config.http.backoff_factor,
    sleep_before_search=config.pipeline.search_delay,
    logger=logger.info,
)
```

Qué cambió en el comportamiento:

- **Una búsqueda fallida es un error, no el final de los datos.**
  `search_arxiv` devolvía `None`, y el bucle de `main.py` lo interpretaba como
  "no hay más artículos" y pasaba a informar de un éxito. El registro antiguo
  muestra 9 ejecuciones que se detuvieron así. Ahora
  `AsyncETLPipeline.run()` lanza `PipelineAborted` y `main.py` termina con el
  código de estado 1.
- **Los reintentos esperan más que los valores por defecto.** El extractor
  espera `backoff_factor ** attempt` segundos entre intentos, así que el factor
  por defecto de 2 espera 1 s y luego 2 s. arXiv limita con `429` durante más
  tiempo que eso, y el código antiguo esperaba 20 s después de un 429, así que
  udg-catalogue fija `backoff_factor: 5.0` y `max_retries: 4` (esperas de 1, 5
  y 25 s).
- **La verificación TLS vuelve a estar activada.** La descarga antigua del
  e-print usaba `verify=False`.
- **Más envíos producen LaTeX.** Un único archivo `.tex` comprimido con gzip
  se lee en lugar de recurrir al PDF, y las fuentes de varios archivos se
  ensamblan en el orden de los `\input`.
- **Todo lo demás es igual.** Los patrones de recorte de referencias son las
  mismas siete expresiones, y el analizador de PDF añade las tablas bajo el
  mismo marcador `--- EXTRACTED TABLES ---`. Con tres artículos recientes, el
  código antiguo y el nuevo devolvieron un texto idéntico byte a byte.

## Paso 4: los pasos con el LLM {#step-4-the-llm-steps}

**Antes** (`arxiv_client.py`, recortado):

```python
def is_paper_relevant(title: str, abstract: str) -> bool:
    if not abstract:
        return True
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": STRICT_SIMULATION_PROMPT},
                {"role": "user", "content": f"Title: {title}\nAbstract: {abstract}"}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=20
        )
        data = json.loads(response.choices[0].message.content.strip())
        return bool(data.get("relevant", False))
    except Exception as e:
        logger.warning(f"Filter error: {e}. Proceeding to download.")
        return True


def extract_udg_data(text: str | bytes) -> list[dict]:
    try:
        ...
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return []
```

**Después** (las mismas llamadas que en `run_ingestion` y `build_pipeline`,
extraídas a variables):

```python
llm_client = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    default_timeout=config.llm.timeout,
)
relevance_filter = AsyncLLMRelevanceFilter(llm_client=llm_client, system_prompt=RELEVANCE_PROMPT)
entity_extractor = AsyncLLMEntityExtractor(
    llm_client=llm_client,
    system_prompt=EXTRACTION_PROMPT,
    result_key="galaxies",
    timeout=config.llm.timeout,
)
```

Los prompts se trasladaron a `udg_catalogue/prompts.py` carácter por carácter.
Ya mencionaban JSON, algo que exige el modo JSON, y el prompt de extracción ya
pedía `{"galaxies": [...]}`, así que `result_key="galaxies"` lee esa forma y no
hizo falta cambiar el prompt. El límite de 120 000 caracteres, la eliminación
del HTML y la temperatura 0 también son los valores por defecto de la
biblioteca.

Qué cambió en el comportamiento:

- **La relevancia sigue dejando pasar ante un fallo.** Una llamada fallida deja
  pasar el artículo, como antes, y el tiempo de espera sigue siendo de 20 s. Una
  diferencia: una respuesta sin un veredicto claro ahora también deja pasar el
  artículo, mientras que el código antiguo interpretaba la ausencia de la clave
  `relevant` como `False`. Pasa `default_on_error=False` para retener esos
  artículos; desde la 0.5.1 se reintentan entonces en la siguiente ejecución.
- **Los fallos de extracción se reintentan.** `extract_udg_data` devolvía `[]`
  cuando DeepSeek fallaba, así que el artículo se marcaba como procesado sin
  haber extraído nada; el registro antiguo muestra 8 artículos así a los que
  nunca se volverá. `AsyncLLMEntityExtractor` lanza `LLMError`, el pipeline
  deja el artículo sin marcar y la siguiente ejecución lo vuelve a intentar.

## Paso 5: reglas del dominio como complementos {#step-5-domain-rules-as-plug-ins}

Las reglas que deciden qué cuenta como la misma galaxia, y qué cuenta como una
galaxia real, son ciencia, y se quedan en el proyecto. La biblioteca les da un
lugar donde conectarse.

### Correspondencia de nombres: un `KeyNormalizer` {#name-matching-a-keynormalizer}

**Antes** (`data_processor.py`):

```python
def universal_normalize_name(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    digits_match = re.search(r"\d+", s)
    if digits_match:
        digits = str(int(digits_match.group()))
        if s.startswith("vcc"):
            return f"vcc{digits}"
        return f"dragonfly{digits}"

    return s
```

Traslada primero una función así **sin cambios**, como subclase de
`KeyNormalizer`, para que la comprobación de paridad del paso 8 compare la
infraestructura y nada más. udg-catalogue hizo exactamente eso.

Resultó que esta función fusionaba galaxias distintas (consulta
[Lo que reveló la migración](#what-the-migration-uncovered)), así que se
sustituyó en cuanto se confirmó la paridad. **Después**
(`udg_catalogue/naming.py`):

```python
DEFAULT_PREFIX_ALIASES: dict[str, str] = {"dragonfly": "df"}
_NAME_TOKEN = re.compile(r"[^\W\d_]+|\d+")
_NUMBER_SEPARATOR = "."


class GalaxyNameNormalizer(KeyNormalizer):
    def __init__(self, prefix_aliases: Mapping[str, str] | None = None) -> None:
        self._prefix_aliases = dict(DEFAULT_PREFIX_ALIASES if prefix_aliases is None else prefix_aliases)
        self._missing_value_guard = DefaultKeyNormalizer()

    def normalize(self, raw_value: Any) -> str:
        if not self._missing_value_guard.normalize(raw_value):
            return ""
        tokens = _NAME_TOKEN.findall(unicodedata.normalize("NFKC", str(raw_value)).casefold())
        if not tokens:
            return ""
        tokens[0] = self._prefix_aliases.get(tokens[0], tokens[0])
        key: list[str] = []
        previous_is_number = False
        for token in tokens:
            is_number = token.isdecimal()
            if is_number and previous_is_number:
                key.append(_NUMBER_SEPARATOR)
            key.append(str(int(token)) if is_number else token)
            previous_is_number = is_number
        return "".join(key)
```

`DF 44`, `DF044` y `Dragonfly 44` siguen compartiendo la clave `df44`, mientras
que `KDG 44`, `NGC 1052-DF2` y `NGC 1052-DF4` conservan ahora claves propias.
Delegar la comprobación de valores ausentes en `DefaultKeyNormalizer` hace que
`None`, `NaN` y los valores no escalares se traten como espera cada componente
de la biblioteca. El exportador CSV y la deduplicación del posprocesamiento
usan ambos `GalaxyNameNormalizer`, así que las dos etapas siempre coinciden en
la identidad.

### Validación: `RecordValidator` y un envoltorio {#validation-recordvalidators-and-a-wrapper}

**Antes** (`data_processor.py`): la validación estaba enterrada dentro de
`upsert_to_csv`.

```python
def is_valid_galaxy(galaxy: dict) -> bool:
    ...
    if FORBIDDEN_PATTERN.search(name):
        logger.info(f"Object '{name}' filtered out as simulation/model.")
        return False

    ra, dec = galaxy.get("ra"), galaxy.get("dec")
    if ra is not None:
        try:
            if not (0.0 <= float(ra) <= 360.0):
                return False
        except (ValueError, TypeError):
            return False
    ...
    return any(galaxy.get(f) is not None for f in KEY_FIELDS)
```

**Después** (`udg_catalogue/validation.py`): los validadores de la biblioteca
cubren las reglas de palabras clave y de rangos, y una pequeña clase cubre el
resto.

```python
class HasAnyMeasurement(RecordValidator):
    def __init__(self, fields: Iterable[str]) -> None:
        self._fields = tuple(fields)

    def is_valid(self, record: dict[str, Any]) -> bool:
        return any(record.get(field) is not None for field in self._fields)


def build_galaxy_validator() -> RecordValidator:
    return CompositeValidator(
        [
            KeywordExclusionValidator(KEY_COLUMN, list(SIMULATION_KEYWORDS)),
            NumericRangeValidator(SKY_COORDINATE_RANGES),
            HasAnyMeasurement(MEASUREMENT_FIELDS),
        ]
    )
```

`AsyncETLPipeline` no llama por sí mismo a los validadores, así que un
`AsyncEntityExtractor` mínimo los aplica entre la extracción y la exportación y
registra lo que descarta:

```python
class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(
        self,
        inner: AsyncEntityExtractor,
        validator: RecordValidator,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self._inner = inner
        self._validator = validator
        self._log = logger or (lambda _message: None)

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        for entity in await self._inner.extract(text):
            if self._validator.is_valid(entity):
                accepted.append(entity)
            else:
                self._log(f"Entity rejected by validation: {entity.get(KEY_COLUMN)!r}")
        return accepted
```

Antes de confiar en `KeywordExclusionValidator` en lugar de la antigua
expresión regular, compara ambas con tus datos existentes. En udg-catalogue
coincidieron en los 1285 nombres guardados y en casos límite como `TNG50-1`,
`illustris_galaxy_1` y `Firefly 7`.

## Paso 6: exportación y estado {#step-6-export-and-state}

**Antes** (`data_processor.py` e `incremental.py`, recortados): cada hilo de
trabajo leía el CSV entero, lo modificaba y lo volvía a escribir, sin ningún
cerrojo entre los seis hilos.

```python
def upsert_to_csv(records: list[dict]) -> None:
    ...
    df = pd.read_csv(CSV_FILE) if os.path.isfile(CSV_FILE) and os.path.getsize(CSV_FILE) > 0 else pd.DataFrame(columns=fieldnames)
    ...
    df.drop(columns=["_norm_name"]).to_csv(CSV_FILE, index=False, encoding="utf-8")


def save_processed_id(arxiv_id: str) -> None:
    if arxiv_id:
        with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
            f.write(arxiv_id + "\n")


def save_pipeline_metadata(start_index: int) -> None:
    meta = {"last_run_date": datetime.now().isoformat(), "last_start_index": start_index}
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4)
```

**Después** (`build_catalogue_exporter` y el gestor de estado de
`build_pipeline`, con las constantes de `udg_catalogue/config.py` y las rutas
por defecto escritas explícitamente):

```python
exporter = AsyncCsvUpsertExporter(
    key_column="galaxy_name",
    value_columns=["ra", "dec", "distance_mpc", "effective_radius_kpc", "stellar_mass_solar", "dark_matter_fraction"],
    normalizer=GalaxyNameNormalizer(),
    numeric_clip={"dark_matter_fraction": (0.0, 1.0)},
)
state_manager = AsyncFileStateManager("processed_arxiv_ids.txt", "pipeline_meta.json")
```

El exportador conserva la antigua regla de fusión: una fila por nombre
normalizado, los registros posteriores solo rellenan celdas vacías, los valores
se convierten a números de coma flotante y `numeric_clip` sustituye la
restricción escrita a mano de la fracción de materia oscura. Además, serializa
las exportaciones concurrentes y publica cada instantánea con un renombrado
atómico.

**Comprueba si puedes reutilizar tal cual tus archivos de estado.** En
udg-catalogue fue posible: `processed_arxiv_ids.txt` ya contenía
identificadores con versión sin más, como `2607.14209v1`, el formato que
produce `AsyncArxivExtractor`, y `pipeline_meta.json` ya tenía las claves
`last_run_date` y `last_start_index` que lee `AsyncFileStateManager`. Apuntar
el gestor de estado a los archivos antiguos trasladó los 542 artículos
procesados sin ningún script de importación. Si tus identificadores están
guardados como URL o sin el sufijo de versión, conviértelos primero, o todos
los artículos se procesarán de nuevo.

Cambiaron dos detalles de la reanudación:

- **Listados de más recientes primero.** arXiv lista primero los envíos más
  recientes, así que un desplazamiento guardado se va desfasando a medida que
  llegan artículos nuevos. Ahora `main.py` pasa `start_index=0` por defecto y
  vuelve a recorrer desde el envío más reciente omitiendo por identificador los
  artículos procesados; una nueva pasada cuesta solicitudes de listado, no
  llamadas al LLM. `python main.py --resume` usa en su lugar el desplazamiento
  guardado.
- **Los desplazamientos solo avanzan más allá de páginas resueltas.** El bucle
  antiguo sumaba 500 al desplazamiento después de cada página, aunque hubieran
  fallado artículos en ella. La biblioteca solo avanza más allá de una página
  cuando todos sus artículos se han procesado o se han descartado por
  irrelevantes.

## Paso 7: posprocesamiento {#step-7-post-processing}

**Antes** (`data_processor.py`, recortado): la deduplicación reescribía el CSV
sin procesar en su sitio después de hacer una copia `.bak`, y
`process_database` ejecutaba una secuencia de funciones.

```python
def process_database() -> None:
    df = pd.read_csv(CSV_FILE)
    ...
    if "dark_matter_fraction" in df.columns:
        df["dark_matter_fraction"] = df["dark_matter_fraction"].clip(0.0, 1.0)

    df = calculate_completeness(df)
    df = assign_constellations(df)
    df = assign_3d_clusters(df)
    df = assign_quality_flag(df)
    ...
    df_sorted.to_csv(SORTED_CSV_FILE, index=False, encoding="utf-8")
```

**Después** (`udg_catalogue/postprocess.py`): la misma secuencia como un
`ProcessorChain`, dejando intacto el CSV sin procesar y escribiendo solo el
catálogo ordenado.

```python
def build_catalogue_chain(config: CatalogueConfig, normalizer: KeyNormalizer | None = None) -> ProcessorChain:
    return ProcessorChain(
        [
            NormalizationStep(KEY_COLUMN, normalizer or GalaxyNameNormalizer(), NORMALIZED_KEY_COLUMN),
            DeduplicationStep(
                NORMALIZED_KEY_COLUMN,
                matcher=SkyPositionMatcher(),
                match_threshold=config.deduplication.max_separation_arcsec,
            ),
            ValueClipStep(FRACTION_BOUNDS),
            CompletenessStep(list(MEASUREMENT_FIELDS)),
            ConstellationStep(),
            ClusteringStep(
                CartesianDistanceFeatures(),
                eps=config.clustering.max_distance_mpc,
                min_samples=config.clustering.min_samples,
            ),
            QualityFlagStep(),
            CatalogueLayoutStep(),
        ]
    )
```

`CompletenessStep`, `QualityFlagStep`, `NormalizationStep`,
`DeduplicationStep` y `ClusteringStep` proceden de la biblioteca. La ciencia se
conecta a través de dos pequeñas interfaces. `SkyPositionMatcher` indica a
`DeduplicationStep` qué filas son el mismo objeto en el cielo:

```python
class SkyPositionMatcher(NeighborMatcher):
    def find_matches(self, frame: pd.DataFrame, threshold: float) -> list[tuple[int, int]]:
        located = frame[located_rows(frame, self._ra_column, self._dec_column)]
        if len(located) < 2:
            return []
        coordinates = sky_coordinates(located, self._ra_column, self._dec_column)
        neighbours, separations, _ = coordinates.match_to_catalog_sky(coordinates, nthneighbor=2)
        separation_arcsec = separations.to_value(u.arcsec)
        labels = located.index.to_numpy()
        return [
            (int(labels[position]), int(labels[neighbour]))
            for position, neighbour in enumerate(neighbours)
            if separation_arcsec[position] <= threshold and labels[position] < labels[neighbour]
        ]
```

`CartesianDistanceFeatures` da a `ClusteringStep` posiciones 3D construidas a
partir de la ascensión recta, la declinación y la distancia.
`ConstellationStep`, `ValueClipStep` y `CatalogueLayoutStep` son `Processor`
corrientes que se quedan en el proyecto: un `Processor` solo tiene que devolver
un DataFrame nuevo sin modificar el de entrada.

Mantener el CSV sin procesar como la fuente de verdad del exportador, y derivar
de él el archivo ordenado, hace que el posprocesamiento sea repetible:
`python main.py --skip-ingestion` reconstruye todos los resultados sin tocar
arXiv ni el LLM.

## Paso 8: comprueba la paridad antes de cambiar el comportamiento {#step-8-check-parity-before-changing-behavior}

Mantén el código antiguo ejecutable junto al nuevo y dale a ambos las mismas
entradas. No necesitas tener instalado el proyecto antiguo: exporta los módulos
antiguos desde Git a una carpeta temporal con
`git show <commit>:data_processor.py` e impórtalos desde allí.

udg-catalogue hizo cuatro comprobaciones.

**Reproducción de la exportación.** Cada fila del catálogo existente se dividió
al azar en dos registros de extracción parciales, se añadieron unos cuantos
registros no válidos escritos a mano, y los registros barajados se pasaron por
lotes tanto por el antiguo upsert como por el nuevo validador y exportador:

```python
for batch in batches:
    data_processor.upsert_to_csv([dict(record) for record in batch])

for batch in batches:
    await exporter.export([record for record in batch if validator.is_valid(record)], "new.csv")
```

**Posprocesamiento.** Los antiguos `clean_duplicates` y `process_database` y la
nueva cadena se ejecutaron sobre copias del mismo catálogo sin procesar, y los
resultados ordenados se compararon celda a celda. Compara la *pertenencia* a
los grupos, no los identificadores de grupo: DBSCAN numera los grupos según el
orden en que los encuentra.

**Texto completo.** La recuperación antigua y la nueva obtuvieron los mismos
tres artículos recientes.

**Ejecución real.** El pipeline ensamblado se ejecutó contra arXiv y DeepSeek
con valores pequeños de `page_size` y `total_limit`, sobre una carpeta de
estado nueva.

| Comprobación | Resultado |
|--------------|-----------|
| Reproducción de la exportación: 2581 registros en 735 lotes | CSV idéntico |
| Reproducción de la exportación con una galaxia repetida dentro de un artículo | idéntico tras fusionar 2 filas duplicadas que creaba el antiguo upsert |
| Posprocesamiento del catálogo de 1285 galaxias | idéntico celda a celda, incluidos el orden de las filas y los identificadores de grupo, salvo 3 filas cuya RA supera 360° |
| Texto completo de 3 artículos recientes | texto LaTeX idéntico byte a byte |
| Ejecución real | arXiv respondió `429` a todos los intentos de listado, y `run()` lanzó `PipelineAborted` sin escribir nada, en lugar de informar de un éxito; esto es lo que motivó la espera más larga del paso 3 |
| Batería de pruebas del proyecto | 84 pruebas sin conexión, 100 % de cobertura, que pasan tanto con la biblioteca editable como en un entorno limpio instalado desde el wheel incluido en el repositorio |

Solo después de que todo esto coincidiera se introdujo la corrección del
normalizador, como un cambio aparte. Al regenerar con ella el catálogo
ordenado, las únicas diferencias fueron las tres filas con RA no válida, grupos
renumerados con la misma pertenencia y la columna `filled_fields` eliminada.

Cuando ejecutes el pipeline migrado:

- Busca `Record processing failed` en el registro. Esos registros no se
  marcaron como procesados, y la siguiente ejecución los reintenta.
- Si `run()` lanza `PipelineAborted`, lee el `__cause__` de la excepción: allí
  aparecen una clave de API rechazada, un CSV ilegible o una solicitud de
  listado limitada.
- Si escribiste tus propios componentes, compáralos con los contratos de
  [Añadir un componente nuevo](../project/contributing.md#adding-a-new-component).

## Paso 9: borra el código antiguo {#step-9-delete-the-old-code}

Cuando las comprobaciones pasen, borra lo que la biblioteca ha sustituido.
udg-catalogue eliminó `arxiv_client.py`, `data_processor.py`, `config.py`,
`logger.py`, `incremental.py`, el patrón duplicado de palabras clave de
simulación y el prompt de filtro sin usar, junto con las pruebas que simulaban
`requests` y el grupo de hilos. Lo que queda es un paquete `udg_catalogue` de
módulos del dominio (configuración, prompts, nombres, validación, astrometría,
posprocesamiento, mapas, análisis) y una batería de pruebas que ejercita el
pipeline real sin conexión.

`visualization.py` y el panel construían la misma figura de Plotly dos veces;
la migración fue un buen momento para darles un único constructor de figuras
compartido. No se usó `AsyncPlotly3DExporter`, porque el mapa de udg-catalogue
necesita texto emergente personalizado y un intervalo de colores fijo.

## Actualizar el proyecto {#upgrading-the-project}

El paso 1 fija un intervalo de versiones y sube su límite superior solo después
de comprobar una nueva versión menor con las pruebas del proyecto. La
[guía de migración](../project/migration.md) enumera lo que cambia cada
versión; esta sección recoge lo que esos cambios supusieron para udg-catalogue.

### Pasar a la 0.4 {#moving-to-04}

udg-catalogue se saltó la 0.3: su `build_pipeline` no pasaba ningún
`memory_ingestor` y `AsyncFileStateManager` no cambió, así que nada de la 0.3
le afectaba. Pasó de `>=0.2.0,<0.3` directamente a `>=0.4.0,<0.5`, añadiendo
los extras `embeddings`, `embeddings-local` y `search`:

```text
sci-etl-core[async,llm,pdf,cluster,embeddings,embeddings-local,search]>=0.4.0,<0.5
```

La actualización a la 0.4 retiró varias piezas de código que los pasos
anteriores habían hecho escribir al proyecto:

- **Ajustes del pipeline renombrados.** El `build_pipeline` y el
  `run_ingestion` de la 0.2 emiten advertencias en la 0.4, porque
  `max_records` y `max_workers` pasaron a ser `total_limit` y
  `max_concurrency`. udg-catalogue renombró ambas claves en `config.yaml`.
- **Sin subclase del pipeline.** `PipelineConfig` incorporó `page_size`,
  `search_delay` y `newest_first`, así que se borró el
  `CataloguePipelineConfig` del paso 2 y `CatalogueConfig` usa la sección
  `pipeline` de la biblioteca tal cual.
- **Validación sin envoltorio.** udg-catalogue pasa `build_galaxy_validator()`
  y `label_field=KEY_COLUMN` a `AsyncLLMEntityExtractor` y borró el
  `ValidatedEntityExtractor` del paso 5.
- **Reanudación con los más recientes primero.** udg-catalogue fija
  `pipeline.newest_first: true`, así que `python main.py` reanuda ahora por
  defecto; la opción `--resume` del paso 6 ha desaparecido, y `--rescan` pasa
  `start_index=0` con `newest_first=False` para paginar el listado completo.
- **Caché, apagado y resúmenes de ejecución.** udg-catalogue envuelve su
  cliente del LLM en un `CachingLLMClient` respaldado por un
  `AsyncSqliteLLMResponseCache`, de modo que una nueva ejecución después de un
  fallo no paga dos veces las mismas llamadas de relevancia y extracción. Pasa
  un `ShutdownSignal`, y `main.py` termina con el código 130 ante
  `PipelineInterrupted`. Una función `on_event` registra cada `PageFinished`, y
  el `RunMetrics` del evento `RunFinished`, incluido el consumo de tokens de
  `usage_sources`, se convierte en el resumen de la ejecución en el registro.
- **Gráficos.** `ScatterPlotConfig` incorporó el texto emergente personalizado
  y el intervalo de colores fijo cuya ausencia hizo que udg-catalogue no usara
  `AsyncPlotly3DExporter` en el paso 9.
- **Restricción de valores y diseño de la tabla.** udg-catalogue borró sus
  propios `ValueClipStep` y `CatalogueLayoutStep` del paso 7; la cadena importa
  ahora `ValueClipStep` de la biblioteca y termina con
  `TableLayoutStep(sort_by=SORT_ORDER, leading_columns=LEADING_COLUMNS,
  hidden_prefixes=("_",))`.

Después de la actualización, la conexión del pipeline de udg-catalogue lee sus
ajustes de la configuración e indexa cada artículo relevante para la búsqueda.
Reducido a la rama de ingesta, `udg_catalogue/pipeline.py` construye el
pipeline así:

```python
def build_pipeline(config, logger, http_client, llm_client, library, shutdown=None):
    cache = AsyncSqliteLLMResponseCache(config.paths.llm_cache)
    cached_llm = CachingLLMClient(llm_client, cache, model=config.llm.model, logger=logger.warning)
    extractor = AsyncArxivExtractor.from_config(
        config.http,
        config.pipeline,
        client=http_client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        logger=logger.info,
    )
    return AsyncETLPipeline.from_config(
        config.pipeline,
        extractor=extractor,
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=cached_llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=build_entity_extractor(config, cached_llm, logger),
        exporter=build_catalogue_exporter(),
        state_manager=AsyncFileStateManager(config.paths.processed_ids, config.paths.pipeline_metadata),
        destination=str(config.paths.raw_catalogue),
        logger=logger.warning,
        closeables=[http_client, llm_client, cache, *library.closeables],
        memory_ingestor=library.memory_ingestor(build_chunker(config.embeddings), logger.warning),
        shutdown=shutdown,
        on_event=progress_logger(logger.info),
        usage_sources=[llm_client, *library.usage_sources],
    )
```

`library.memory_ingestor` devuelve un `AsyncCompositeIngestor` que guarda los
fragmentos con embeddings en un `AsyncSqliteEmbeddingStore` e indexa el
artículo en un `AsyncSqliteFts5Store`, o solo el `AsyncSearchIndexer` cuando
`embeddings.enabled` es false. La propia ejecución se reduce a un único bloque
`async with`:

```python
async def _run(build, config, logger, start_index, shutdown):
    library = open_paper_library(config)
    http_client = build_http_client(config)
    llm_client = build_llm_client(config)
    async with build(config, logger, http_client, llm_client, library, shutdown) as pipeline:
        return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

Los artículos cribados antes de la actualización nunca se indexaron, y
udg-catalogue no tenía memoria vectorial desde la que rellenar.
`python main.py --index-papers` los vuelve a obtener mediante el mismo pipeline
con un extractor de entidades que no devuelve nada, un filtro de relevancia que
omite los artículos que ya están en el índice de texto y un gestor de estado
aparte (`indexed_arxiv_ids.txt`, `indexing_meta.json`), de modo que el catálogo
de galaxias y sus identificadores procesados no se tocan.

### Pasar a la 0.5 {#moving-to-05}

udg-catalogue pasó a `>=0.5.1,<0.6`. Le afectaron dos cambios:

- **Configuración estricta.** Las secciones de configuración de la biblioteca
  rechazan claves desconocidas, y udg-catalogue hizo también estrictas sus
  propias secciones (`paths`, `embeddings`, `clustering`, `deduplication`), así
  que una errata en `config.yaml` falla al arrancar con el nombre de la clave.
  Los nombres de la 0.2 `max_records` y `max_workers` ya no se cargan.
- **Páginas de listado analizadas.** Los extractores devuelven un
  `ListingPage` desde `fetch_page(query, cursor, page_size)` en lugar de bytes
  sin procesar desde `search` y `parse_listing`, así que el envoltorio del
  proyecto que registra cada solicitud de listado reenvía ahora
  `cursor_for_offset` y `fetch_page`.

### Pasar a la 0.6 {#moving-to-06}

udg-catalogue pasó a `>=0.6.0,<0.7`. Desde la 0.6, una instalación base solo
necesita Pydantic, así que el proyecto enumera todos los extras que importa,
añadiendo `config` (YAML y `.env`), `arxiv` (análisis de Atom), `html` y
`processors` (pandas):

```text
sci-etl-core[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]>=0.6.0,<0.7
```

El resto de la actualización cambió lo que registra el catálogo:

- **Una fila por galaxia y artículo.** `AsyncCsvUpsertExporter` ha
  desaparecido. `AsyncCsvExporter` escribe una fila por galaxia, etiquetada
  con el `record_id` del artículo, nunca fusiona, recorta ni convierte un valor,
  y reemplaza las filas de un artículo cuando el artículo se vuelve a extraer.
  Toda la fusión pasó al posprocesamiento. El catálogo sin procesar escrito por
  la 0.5 no tiene columna `record_id`, así que el catálogo se reconstruye desde
  cero una vez, y el posprocesamiento rechaza un archivo sin procesar antiguo
  con un mensaje que lo explica.
- **Los artículos detrás de cada galaxia.** La cadena de posprocesamiento
  empieza con un pequeño `RawRowsStep` que oculta `record_id` y `extra` como
  `_record_id` y `_extra` y lee las mediciones como números. Después,
  `DeduplicationStep(source_column="_record_id", sources_column="source_papers")`
  enumera en el catálogo publicado los artículos fusionados en cada galaxia.
- **Rechazos con motivos, guardados para su revisión.**
  `GalaxyValidator.validate` devuelve un `Violation` cuyo código nombra la
  regla infringida (`no-name`, `paper-local-name`, `simulation-keyword`,
  `not-a-number`, `not-positive`, `out-of-range` o `no-measurement`), donde
  `is_valid` solo decía `False`. El extractor registra cada rechazo con su
  motivo y lo guarda en un `AsyncSqliteRejectionStore`, donde un revisor puede
  listarlo y resolverlo.
- **Registro estándar.** Los argumentos `logger=` y `configure_logging` han
  desaparecido. El `configure_run_logging` del proyecto conecta los manejadores
  del registro de la ejecución a su propio logger y a `sci_etl_core`, y un
  `logging.Filter` antepone a las líneas de la biblioteca el identificador de
  arXiv del artículo que se está procesando.
- **La indexación nunca toca el catálogo.** La ejecución `--index-papers`
  pasaba el exportador del catálogo junto con un extractor que no devuelve
  nada. Desde la 0.6, el pipeline escribe todo registro procesado, incluido uno
  sin entidades, y esa escritura borra las filas de ese artículo. Por eso, el
  pipeline de indexación recibe un exportador que no conserva nada:

    ```python
    class DiscardingExporter(AsyncExporter[Any]):
        async def write(self, record: RawRecord, entities: Sequence[Any]) -> None:
            return None
    ```

- **Un manifiesto de ejecución.** Después de cada construcción,
  `write_manifest` registra en `data/run_manifest.json` la versión de
  sci-etl-core, el modelo y la URL base, los hashes de ambos prompts, la
  consulta, los identificadores de arXiv procesados, y el número de filas y el
  SHA-256 de ambos catálogos; ese archivo se incluye en el repositorio junto al
  catálogo publicado.

## Lo que reveló la migración {#what-the-migration-uncovered}

Trasladar el código a componentes compartidos obliga a formular cada regla con
precisión. La migración de udg-catalogue sacó a la luz estos problemas, la
mayoría invisibles en la salida antigua:

1. **La correspondencia de nombres fusionaba galaxias distintas.** El
   normalizador antiguo asignaba a cualquier nombre con cifras, salvo los
   nombres VCC, la clave `dragonfly<primer número>`: 1201 de los 1285 nombres
   guardados (93 %). `KDG 44` coincidía con `DF 44`, y `NGC 1052-DF2` con
   `NGC 1052-DF4`, así que el upsert rellenaba en silencio los huecos de una
   galaxia con las mediciones de otra. El normalizador corregido mantiene
   distintos los 1285 nombres guardados, pero las filas que fusionaron
   ejecuciones anteriores solo se pueden separar volviendo a extraer el
   catálogo.
2. **Los fallos parecían éxitos.** Nueve fallos de búsqueda en arXiv terminaron
   ejecuciones como si el listado se hubiera agotado, y 8 errores de DeepSeek
   marcaron artículos como procesados sin haber extraído nada.
3. **Las escrituras concurrentes del CSV no tenían cerrojo.** Seis hilos
   reescribían el mismo CSV, y el registro recoge 8 excepciones de los hilos de
   trabajo en ese bucle.
4. **La verificación TLS estaba desactivada** en las descargas de e-prints.
5. **El upsert duplicaba galaxias** nombradas dos veces en la extracción de un
   mismo artículo, algo que solo encontró la reproducción de la exportación.
6. **Tres galaxias guardadas tienen una RA superior a 360°.** El antiguo paso
   de constelaciones les daba la vuelta en silencio; ahora se notifican como
   `Unknown`.
7. **Las versiones fijadas de las dependencias no se podían instalar** en la
   versión de Python que indicaba el README: `numpy==1.22.0` no tiene wheels
   para Python 3.11, y `pandas==2.0.0` necesita allí un numpy más reciente.
8. **Una instalación editable se rompió** después de que el espacio de trabajo
   se trasladara a otra carpeta.

## Adaptarlo a tu campo {#adapting-this-to-your-field}

- [ ] Enumera todas las funciones de tu pipeline y clasifícalas en los tres
      grupos de [Relaciona tu pipeline con la biblioteca](#map-your-pipeline-onto-the-library).
- [ ] Instala la biblioteca en modo editable y decide cómo la obtendrán los
      despliegues (un intervalo de versiones de PyPI, o un wheel incluido en el
      repositorio donde PyPI no esté al alcance).
- [ ] Traslada los ajustes a secciones de `BaseAppConfig`; conserva el nombre
      de la variable de entorno de tu clave de API con `api_key_env_var`.
- [ ] Traslada los prompts sin cambios y fija `result_key` en la clave de lista
      que ya pide tu prompt de extracción.
- [ ] Traslada tu regla de correspondencia de nombres como un `KeyNormalizer` y
      tus reglas de registros como `RecordValidator`, sin cambios al principio.
- [ ] Comprueba si tus archivos de identificadores procesados y de
      desplazamiento ya coinciden con el formato del gestor de estado antes de
      escribir un script de importación.
- [ ] Expresa el posprocesamiento como un `ProcessorChain`, con la lógica de tu
      dominio en complementos `NeighborMatcher`, `FeatureExtractor` y
      `Processor`.
- [ ] Reproduce datos reales con el código antiguo y el nuevo y compara los
      resultados.
- [ ] Solo entonces corrige las reglas que hayan resultado deficientes, un
      commit cada vez.
- [ ] Borra el código antiguo y las pruebas que solo lo cubrían a él.

¿Tienes preguntas o has encontrado una aspereza en tu migración? Abre una
[incidencia](https://github.com/xueromll/sci-etl-core/issues): estaremos
encantados de ayudarte.
