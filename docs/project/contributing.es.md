# Contribuir a sci-etl-core

¡Gracias por tu interés en mejorar `sci-etl-core`! Los nuevos extractores,
analizadores, exportadores, backends de embeddings y correcciones de la
documentación son realmente bienvenidos, también de quienes contribuyen por
primera vez. Esta guía te pone a trabajar rápidamente.

Al participar, aceptas cumplir nuestro [Código de conducta](code-of-conduct.md).

## Preparación del entorno de desarrollo {#development-setup}

```bash
git clone https://github.com/xueromll/sci-etl-core.git
cd sci-etl-core

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[full,dev]"
```

- **Se requiere Python 3.11+**: el código usa uniones `X | Y` y dataclasses
  con `slots=True` y `kw_only=True`.
- **Por qué `[full]`:** la batería de pruebas ejercita todos los componentes
  incluidos.
- **No se necesitan para las pruebas:** `sentence-transformers` y un
  controlador SQL real se simulan o se sustituyen por stubs.

## Cómo funciona el código: lee esto primero {#how-the-codebase-works-read-this-first}

- **La asíncrona es la única implementación.** Todos los componentes son
  `async`. No añadas gemelos síncronos de los componentes; no hay generador de
  código. Las implementaciones bloqueantes llegan a un pipeline a través de los
  adaptadores de `_adapters.py`.
- **Un único punto de entrada bloqueante.** `ETLPipeline` (`pipeline.py`)
  ejecuta `AsyncETLPipeline` mediante `_sync_bridge.run_sync`. Discute primero
  en una incidencia cualquier API bloqueante nueva.
- **Mantén libre el bucle de eventos.** Ejecuta el trabajo intensivo en CPU o
  bloqueante con `asyncio.to_thread`. Los analizadores, pandas, `sqlite3` y la
  E/S de archivos siguen este patrón.
- **Inyecta los colaboradores.** Los clientes, los analizadores, `sleep` y
  `logger` son argumentos del constructor para que las pruebas puedan
  sustituirlos. Acepta `logger: Callable[[str], None] | None` y un `sleep`
  inyectable dondequiera que haya temporizaciones o reintentos.
- **Nunca te tragues la cancelación.** Antes de capturar excepciones amplias,
  captura y vuelve a lanzar `asyncio.CancelledError` (consulta
  `llm/relevance_async.py`).
- **Señala los fallos con excepciones.** Usa la jerarquía de `exceptions.py`.
  No devuelvas `None` ni un resultado vacío ante un fallo de transporte: el
  pipeline depende de `UpstreamError` y `MalformedResponseError` para
  distinguir los fallos del final de los datos.
- **Sé seguro ante la concurrencia.** El pipeline llama de forma concurrente a
  los filtros de relevancia, los extractores de entidades, el `write` de un
  exportador y `mark_processed`. Serializa las escrituras compartidas con un
  `asyncio.Lock` y escribe los archivos con `_atomic_io.atomic_write_text`.
  `AsyncCsvExporter` y `AsyncFileStateManager` son buenos modelos.
- **Registra a través del logger del módulo.** Cada módulo registra con
  `_logger = logging.getLogger(__name__)`, en `WARNING` todo lo que cambia lo
  que una ejecución produce o cuesta, en `ERROR` un fallo de sumidero o de
  almacén que la ejecución notifica, y en `INFO` las notas rutinarias. Nunca
  configures manejadores ni niveles; eso le corresponde a la aplicación.
- **Mantén perezosas las importaciones opcionales.** El `__init__.py` de cada
  paquete asigna los nombres públicos a sus módulos en `_EXPORTS` y los carga
  en el primer acceso, de modo que importar un componente nunca requiere las
  dependencias opcionales de otro. Registra allí los nuevos nombres públicos y
  en las importaciones `TYPE_CHECKING` correspondientes (una prueba comprueba
  que coincidan), y añade cualquier dependencia de terceros nueva a un extra en
  `pyproject.toml`.
- **Nada de constantes específicas de un dominio** en el núcleo; mantenlo
  independiente del campo.

## Ejecutar las pruebas {#running-tests}

La batería de pruebas funciona sin conexión: no necesita red, ni un LLM real,
ni un servicio de embeddings.

```bash
pytest                                                # todo, sin conexión
pytest tests/async                                    # componentes asíncronos
pytest tests/contract                                 # conformidad con las ABC
pytest --cov=sci_etl_core --cov-report=term-missing   # informe de cobertura
```

- **La cobertura se mantiene en el 100 %.** `pytest --cov=sci_etl_core` falla
  por debajo del 100 % (configurado en `pyproject.toml`), así que el código
  nuevo o modificado necesita pruebas que lo cubran. Usa `# pragma: no cover`
  solo para las líneas que no pueden ejecutarse en la plataforma de pruebas,
  como las importaciones específicas de un sistema operativo. La CI mide
  también la cobertura de ramas y la muestra en el resumen del trabajo; todavía
  no es obligatoria.
- **Las pruebas asíncronas** usan un marcador explícito
  `@pytest.mark.asyncio` (el modo automático no está configurado), con
  `AsyncMock` o el fixture `mocker`.
- **Sin red real ni esperas exponenciales.** Simula los clientes HTTP, del LLM
  y de embeddings, e inyecta `sleep=AsyncMock()` para saltarte las esperas.
- **Pruebas de contrato.** Cada implementación de una ABC pública tiene un caso
  en `tests/contract/test_abc_conformance.py`; añade uno por cada
  implementación nueva.
- **Pruebas de propiedades.** Pon los invariantes —sobre todo los que deben
  compartir dos backends, como los almacenes de embeddings en memoria y en
  SQLite— en pruebas de Hypothesis en `tests/test_properties.py`.
- **Instantánea de la superficie pública.** `tests/api/public_surface.txt`
  registra la firma de cada clase, campo, método y función estables, y
  `tests/api/test_public_surface.py` falla cuando el código ya no coincide con
  ella. Cuando cambies la API pública a propósito, regenera la instantánea,
  incluye la diferencia en el commit y añade una entrada en CHANGELOG.md:

  ```bash
  python tests/api/update_surface.py
  ```

  `tests/api/surface.py` enumera los nombres estables. Todo nombre que
  [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) o
  [udg-catalogue](https://github.com/xueromll/udg-catalogue) importe o herede
  debe estar entre ellos. `tests/api/consumer_surface.txt` enumera esos
  nombres. Regenéralo cuando cambie la versión fijada de un consumidor, leyendo
  el catálogo desde su rama remota descargada y no desde un clon local que
  puede estar desactualizado:

  ```bash
  git -C ../udg-catalogue fetch origin
  python tests/api/scan_consumers.py sci-etl-cli=../sci-etl-cli udg-catalogue=../udg-catalogue@origin/main
  ```
- **Pruebas reales.** `tests/live` ejecuta una consulta pequeña contra cada
  fuente incluida y comprueba los registros, los metadatos y el texto completo
  que devuelve. Estas pruebas están deseleccionadas por defecto. El flujo Live
  las ejecuta cada noche y nunca es una comprobación obligatoria. Ejecútalas en
  local con `pytest -m live tests/live`. Las claves para un límite de
  frecuencia más alto son opcionales y se leen de `NCBI_API_KEY`,
  `SEMANTIC_SCHOLAR_API_KEY` y `OPENALEX_MAILTO`. Sin su clave, una fuente que
  sigue respondiendo `429` se omite en lugar de fallar.
- **Benchmark de rendimiento.** `python benchmarks/run_throughput.py` pasa cada
  exportador de pipeline incluido por `AsyncETLPipeline` con 1000, 10 000 y
  50 000 registros y escribe los tiempos en `benchmarks/results/<version>.json`.
  Un exportador se considera lineal cuando su tiempo por registro con el
  tamaño mayor es como máximo 1,5 veces su tiempo con el menor. `--sizes`,
  `--repeats` y `--exporters` acotan una ejecución.
- **Pruebas de los consumidores.** El flujo Downstream ejecuta las baterías de
  pruebas de [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) y
  [udg-catalogue](https://github.com/xueromll/udg-catalogue) en cada push y
  pull request, con este clon instalado en lugar de la versión que fija cada
  proyecto, y falla ante cualquier `DeprecationWarning`. Cada trabajo instala
  los extras que indica el propio requisito del proyecto. Para ejecutar en
  local la batería de la CLI:

  ```bash
  git clone https://github.com/xueromll/sci-etl-cli.git ../sci-etl-cli
  pip install -e ".[config,async,arxiv,html,llm,pdf]"
  pip install --no-deps -e ../sci-etl-cli
  pip install click rich pytest pytest-asyncio pytest-mock pytest-cov
  cd ../sci-etl-cli && python -m pytest -W error::DeprecationWarning
  ```

  Y la batería de udg-catalogue, que además instala la versión para CPU de
  PyTorch:

  ```bash
  git clone https://github.com/xueromll/udg-catalogue.git ../udg-catalogue
  export PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
  pip install -e ".[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]" \
      -r ../udg-catalogue/requirements/app.txt -r ../udg-catalogue/requirements/dev.txt
  cd ../udg-catalogue && python -m pytest -W error::DeprecationWarning
  ```

## Estilo de código {#code-style}

- Nombres según **PEP 8**: funciones y variables en `snake_case`, clases en
  `CapWords`, constantes en `UPPER_CASE`.
- **Anotaciones de tipo en todas las firmas públicas.** El paquete incluye
  `py.typed`; mantenlas precisas.
- **Funciones pequeñas y con una sola responsabilidad.** Prefiere la
  composición y la inyección de dependencias a ramificar sobre lógica fija en
  el código.
- **Docstrings para los contratos y la intención.** Documenta `Raises:` y las
  decisiones no obvias; no escribas comentarios que repitan el código.
- **Inglés estadounidense** para los identificadores y las docstrings.

ruff y mypy se ejecutan en la CI en cada push y pull request, configurados en
`pyproject.toml`. ruff comprueba los conjuntos de reglas `ASYNC`, `UP`, `RUF` y
`PT` además de las reglas de pycodestyle, Pyflakes, isort y bugbear. mypy
comprueba los contratos principales (`models`, `exceptions`, `observability`,
`pipeline_async` y cada módulo `async_base`) con opciones más estrictas: sin
definiciones sin tipar, sin genéricos desnudos, sin devolver `Any` y sin
reexportaciones implícitas. Ejecuta ambos antes de abrir un PR:

```bash
pip install -e ".[full,dev,lint]"
ruff check .
mypy
```

`ruff check --fix .` ordena las importaciones y aplica las demás correcciones
seguras. El formato no se impone, así que deja fuera de tu PR los cambios de
formato que no tengan relación. Anota los cambios visibles para los usuarios en
la versión sin publicar de [CHANGELOG.md](changelog.md).

## Documentación {#documentation}

El sitio de documentación se construye con [MkDocs](https://www.mkdocs.org/) y
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) a partir de
`mkdocs.yml` y la carpeta `docs/`, y se publica en GitHub Pages.

```bash
pip install -e ".[docs]"
git clone https://github.com/xueromll/sci-etl-cli.git ../sci-etl-cli
pip install --no-deps -e ../sci-etl-cli
mkdocs serve                                          # vista previa en http://127.0.0.1:8000
mkdocs build --strict                                 # la comprobación que ejecuta la CI
```

- **Dónde están las páginas.** Las guías son archivos Markdown en `docs/`,
  incluidos en la `nav` de `mkdocs.yml`. `CHANGELOG.md`, `MIGRATION.md`,
  `ROADMAP.md`, esta guía, `SECURITY.md` y `CODE_OF_CONDUCT.md` se quedan en la
  raíz del repositorio; las páginas de `docs/project/` los muestran, y los
  enlaces entre ellos se reescriben para el sitio.
- **Traducciones.** Las versiones en ruso, español, chino simplificado y árabe
  de una página están junto a ella como `page.ru.md`, `page.es.md`,
  `page.zh-Hans.md` y `page.ar.md`, y el complemento mkdocs-static-i18n
  construye cada idioma en su propia ruta, como `/ru/`. Un pull request que cambia una
  página en inglés actualiza también sus cuatro traducciones. Las cuatro son
  traducción automática y esperan una revisión de hablantes nativos, así que el
  inglés es el texto autorizado. [TRANSLATING.md](translating.md) nombra al
  coordinador de cada idioma y contiene el glosario y las reglas que sigue una
  página traducida.
- **La sección de la CLI** procede de la carpeta `docs/` y de la `nav` del
  repositorio sci-etl-cli. La construcción busca un clon junto a este, o en la
  ruta de `SCI_ETL_CLI_DIR`; sin él, omite la sección, lo que `--strict`
  notifica como un fallo. Cambia las páginas de la CLI en ese repositorio.
- **Referencia de la API.** Las páginas de `docs/reference/` se generan a
  partir de las docstrings. Un módulo público nuevo necesita una entrada
  `::: module.path` en una de ellas; `tests/test_docs.py` falla hasta que la
  tenga.
- **Ejemplos de código.** `tests/test_docs.py` comprueba también que cada
  ejemplo de Python de `docs/` compila y que existe cada nombre que importa de
  `sci_etl_core`, así que renombrar un nombre público implica actualizar
  también los ejemplos.
- **Publicación.** El flujo de documentación despliega `master` como la
  versión `dev` y cada etiqueta `v*` como su versión menor, por ejemplo `0.3`,
  con el alias `latest`. Una construcción por etiqueta usa las páginas de la
  CLI de la última versión de sci-etl-cli, o de su rama por defecto cuando esa
  versión no tiene `mkdocs.yml`. No hay que publicar nada a mano.

## Publicar versiones {#releasing}

- **Versiones de desarrollo.** Justo después de una versión, `master` pasa a la
  siguiente versión de desarrollo, como `0.7.0.dev0` después de `0.6.0`, para
  que una construcción desde `master` nunca se presente como una versión.
- **Condición de publicación.** Hacer push de una etiqueta `v*` ejecuta la
  batería de la CI y el flujo Downstream sobre el commit etiquetado. La
  distribución solo se construye y se publica cuando ambos pasan, así que nunca
  se publica una versión que rompa sci-etl-cli o udg-catalogue. La etiqueta
  debe coincidir con la versión de `pyproject.toml`.
- **Obsolescencias.** Desde la 0.6.0, un nombre obsoleto sigue funcionando
  durante al menos dos versiones menores antes de eliminarse.
- **Antes de etiquetar.** Pon fecha a la sección sin publicar de
  `CHANGELOG.md`, actualiza las versiones compatibles en `SECURITY.md` y vuelve
  a ejecutar `python benchmarks/run_throughput.py` para que
  `benchmarks/results/` contenga la nueva versión.
- **Actions fijadas.** Los flujos fijan cada action a un SHA de commit, con la
  etiqueta en un comentario al final de la línea, como `# v5`. Para pasar a una
  versión más reciente, obtén su SHA con
  `git ls-remote https://github.com/actions/checkout refs/tags/v5` y actualiza
  a la vez la fijación y el comentario.

## Formato de los commits {#commit-format}

Usa [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>
```

Tipos habituales: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`.
Marca los cambios incompatibles con `!` (por ejemplo, `refactor(core)!: ...`).

Ejemplos:

```
feat(extractors): add PubMed async extractor
fix(exporters): serialize concurrent CSV upserts
docs(readme): document ETLPipeline event-loop behavior
```

Escribe el resumen en imperativo y con menos de unos 72 caracteres. Haz
referencia a las incidencias en el cuerpo (`Closes #123`).

## Proceso de pull request {#pull-request-process}

1. **Abre primero una incidencia** para cualquier cosa que no sea trivial, para
   que podamos acordar el enfoque.
2. **Crea una rama** a partir de `master`, por ejemplo `feat/pubmed-extractor`.
3. **Escribe pruebas** junto con tu cambio; mantén la cobertura en el 100 %.
4. **Ejecuta** la batería de pruebas en local (y el linter y la comprobación de
   tipos, si los usas).
5. **Actualiza la documentación** de los cambios visibles para los usuarios:
   - las páginas de `docs/` para el uso; mantén `README.md` como un resumen
     breve
   - las traducciones al ruso, al español, al chino y al árabe de cada página
     en inglés que cambies, siguiendo [TRANSLATING.md](translating.md); si no
     puedes escribir alguna de ellas, dilo, y el coordinador de ese idioma la
     añade antes de la fusión
   - `MIGRATION.md` para un cambio incompatible, bajo la versión que lo publica
   - `docs/guide/migrating-a-pipeline.md` cuando el cambio afecte al traslado
     de un pipeline existente a la biblioteca
   - `ROADMAP.md` cuando publiques un elemento de la lista
   - la descripción del pull request para cualquier cambio incompatible, con lo
     que los usuarios tienen que actualizar
6. **Rellena** la [plantilla de pull request](https://github.com/xueromll/sci-etl-core/blob/master/.github/PULL_REQUEST_TEMPLATE.md).
7. **Mantén los PR centrados**: un cambio lógico por PR es lo más fácil de
   revisar.

Una persona responsable del mantenimiento lo revisará pronto. Espera un
intercambio amable y constructivo; los cambios que se pidan se refieren al
código, nunca a ti.

## Añadir un componente nuevo {#adding-a-new-component}

La mayoría de las contribuciones se conectan a una clase base abstracta
existente:

| Componente | Hereda de | Implementa | Contrato |
|------------|-----------|------------|----------|
| Extractor | `AsyncExtractor` | `async fetch_page(query, cursor, page_size) -> ListingPage`, `async fetch_full_text`; `cursor_for_offset` cuando los cursores son desplazamientos decimales | Devuelve todas las entradas que pueda leer: el pipeline omite los identificadores procesados. Cuenta en `entries` las entradas sin identificador, devuelve `next_cursor=None` en la última página y `truncated=True` en la página que alcanza el propio límite de resultados de la fuente. Lanza `UpstreamError` cuando no se puede contactar con la fuente tras los reintentos, `ExtractionError` cuando rechaza una solicitud directamente, `MalformedResponseError` para un listado ilegible y `StaleCursorError` para un cursor que la fuente ya no acepta. |
| Analizador | `Parser` (opcionalmente `TableParser`) | `extract_text(content: bytes) -> str` | Síncrono; quien lo llama lo ejecuta en un hilo de trabajo. Lanza `ParsingError` para los bytes que no pueda leer. |
| Cliente del LLM | `AsyncLLMClient` | `async complete_json(system_prompt, user_content, timeout)`; opcionalmente `complete_structured(..., schema, timeout)` e `invalidate(..., schema=None)` | Devuelve el objeto JSON analizado; lanza `LLMError` ante un fallo o cuando el cuerpo no es un objeto JSON. Sobrescribe `complete_structured` cuando el proveedor admita salida por JSON Schema; la implementación por defecto llama a `complete_json`. |
| Caché de respuestas del LLM | `AsyncLLMResponseCache` | `async get(key)`, `async set(key, response)`, `async clear()` | `get` devuelve `None` para una clave inexistente. Devuelve copias, para que quien modifique una respuesta no pueda modificar la caché. Lanza `LLMCacheError` ante un fallo de almacenamiento; `CachingLLMClient` lo registra y llama al LLM en su lugar. Añade `aclose()` si mantienes conexiones. |
| Filtro de relevancia | `AsyncRelevanceFilter` | `async is_relevant(record)` | Vuelve a lanzar `CancelledError`. |
| Extractor de entidades | `AsyncEntityExtractor[E]` | `async extract(text) -> Sequence[E]`; `extract_record(record, text)` cuando se necesite el registro | El pipeline llama a `extract_record`, cuya implementación por defecto llama a `extract`. Lanza una excepción ante un fallo en lugar de devolver `[]`, para que el registro se reintente. Un extractor que necesita el registro fija `requires_record = True`; un envoltorio delega en el `extract_record` interno. |
| Exportador | `AsyncExporter[E]` | `async write(record, entities)`; opcionalmente `open`, `flush`, `aclose` y `durable_writes` | Recibe el destino en el constructor. `write` se ejecuta para cada registro procesado, incluido uno sin entidades, posiblemente de forma concurrente, y debe ser idempotente. Con `durable_writes = False`, `flush` debe hacer duradera cada escritura anterior. |
| Gestor de estado | `AsyncStateManager` | `load_processed_ids`, `mark_processed`, `load_metadata`, `save_metadata` | Seguro ante la concurrencia. Sobrescribe `record_failure` y `failure_counts` para admitir la cuarentena; las implementaciones por defecto no registran nada. Registra una versión de esquema y rechaza un archivo de una versión más reciente. Sobrescribe `flush()` si usas búfer; añade `aclose()` si mantienes conexiones. |
| Generador de embeddings | `AsyncEmbedder` | `async embed(texts) -> list[list[float]]` | Un vector por entrada, en el mismo orden; lanza `EmbeddingError`. |
| Almacén vectorial | `AsyncEmbeddingStore` | `add`, `delete_record`, `query`, `count` | Reemplaza los fragmentos con el mismo `(record_id, chunk_index)`; `delete_record` elimina todos los fragmentos de un registro. Sobrescribe `replace_record` (por defecto, borrar y luego añadir) si tu backend puede hacer ambas cosas de forma atómica. Nunca devuelvas resultados con puntuaciones no finitas. Compórtate como `InMemoryEmbeddingStore` en cuanto a `top_k`, `min_score` y `exclude_record_id`. Serializa el uso de una conexión compartida y lanza `EmbeddingStoreError`. Implementa `iter_records` (pasajes en el orden de `chunk_index`, registros en el orden de `record_id`, sin vectores) si el índice de texto debe poder rellenarse desde tu almacén. |
| Fragmentador | `TextChunker` | `chunk(text) -> list[str]` | Pasajes ordenados que cubren el texto. |
| Almacén de búsqueda de texto | `AsyncTextSearchStore` | propiedad `facet_keys`, `index`, `delete_record`, `search`, `filter_ids`, `get_documents`, `facet_counts`, `count` | Recibe consultas analizadas, nunca texto. Rechaza con `require_rankable` una consulta que `search` no pueda ordenar. Ordena las puntuaciones iguales por `record_id` y aplica los filtros antes de `limit`. Lanza `ValueError` antes de cualquier E/S para una clave de filtro o de faceta fuera de `facet_keys` o para dos filtros sobre una misma clave (`validate_filters`, `validate_facet_keys`). Acepta `MetadataFilter` y `RangeFilter`, compara los rangos con `tag_in_range` y rellena `TextHit.snippets` para cada campo con una coincidencia resaltada. Sobrescribe `range_counts` (por defecto, un `filter_ids` por rango) si puedes contar en una sola lectura. Devuelve los mismos resultados que `InMemoryTextSearchStore` y lanza `SearchStoreError`. |
| Fuente de aristas | `AsyncEdgeSource` | propiedad `kind`, `async neighbours(record_ids, limit)` | Asigna a cada identificador solicitado, aunque no tenga vecinos, hasta `limit` pares `(record_id, weight)`, los mejores primero, donde un peso mayor significa más relación. Nunca cierres los almacenes que te hayan pasado. |
| Procesador | `Processor` | `process(frame) -> DataFrame` | No modifiques el DataFrame de entrada. |
| Validador | `RecordValidator` | `is_valid(record) -> bool`; opcionalmente `validate(record) -> ValidationResult` | Opera sobre un diccionario de entidad. Sobrescribe `validate` para nombrar el campo y la regla de cada rechazo; debe rechazar exactamente lo mismo que rechaza `is_valid`. |

Registra la nueva clase en el mapa `_EXPORTS` y en las importaciones
`TYPE_CHECKING` de su subpaquete. Un módulo nuevo necesita también una entrada
en su página de `docs/reference/`. Si es una clase principal de cara a los
usuarios, añádela del mismo modo a `sci_etl_core/__init__.py`. Añade un caso
para ella en `tests/contract/test_abc_conformance.py`.

¡Que disfrutes programando, y gracias por contribuir!
