# Guía de migración

Esta guía enumera lo que cambia para el código existente cuando pasas a una
nueva versión de `sci-etl-core`, empezando por la más reciente.
[CHANGELOG.md](changelog.md) enumera todos los cambios, incluidas las
novedades que no requieren ninguna acción.

Fija un intervalo de versiones menores, como `sci-etl-core>=0.6.0,<0.7`, y sube
el límite superior cuando tus pruebas pasen con la siguiente versión menor. Al
pasar de una versión menor a otra posterior, aplica cada sección intermedia,
empezando por la más antigua.

Para trasladar por primera vez a la biblioteca un pipeline de investigación
existente, sigue el ejemplo práctico de
[Migrar un pipeline](https://xueromll.github.io/sci-etl-core/latest/guide/migrating-a-pipeline/).

- [Actualizar a la 0.6](#upgrading-to-06)
- [Actualizar a la 0.5.1](#upgrading-to-051)
- [Actualizar a la 0.5](#upgrading-to-05)
- [Actualizar a la 0.4](#upgrading-to-04)
- [Actualizar a la 0.3](#upgrading-to-03)

---

## Actualizar a la 0.6 {#upgrading-to-06}

La 0.6 cambia el contrato de datos: lo que devuelve un extractor de entidades,
cómo recibe las entidades un exportador, cómo registra mensajes la biblioteca
y qué contiene una instalación base. Es la última versión antes de la 1.0 que
rompe un contrato existente. Exige la nueva versión menor con los extras que
uses:

```text
sci-etl-core[config,async,arxiv,llm,pdf,processors]>=0.6.0,<0.7
```

Los archivos y bases de datos de estado, las cachés del LLM, los almacenes de
embeddings y los índices de texto escritos por la 0.5 se abren sin cambios.
Las respuestas del LLM guardadas en caché siguen siendo válidas: una solicitud
sin esquema tiene la misma clave de caché que en la 0.5.1.

### Instala los extras que importas {#install-the-extras-you-import}

La instalación base ahora solo requiere Pydantic. PyYAML y python-dotenv
pasaron al extra `config`, Beautiful Soup y lxml a `arxiv`, `html` y `xml`, y
pandas a `processors`. Ningún extra instala ya `aiofiles` ni `aiosqlite`.
Importar un componente cuyo extra falta lanza `ModuleNotFoundError` con el
nombre del paquete:

| Usas | Añade el extra |
|------|----------------|
| `load_config`, `load_config_async`, `load_yaml` | `config` |
| `AsyncArxivExtractor` | `async`, `arxiv` |
| `AsyncPubMedExtractor` | `async`, `xml` |
| `JatsXmlParser`, `DocxParser` | `xml` |
| `HtmlTextParser`, o `AsyncLLMEntityExtractor` con texto completo que empieza con marcado | `html` |
| cualquier cosa de `sci_etl_core.processors` salvo los validadores | `processors` |

`full` sigue instalando todos los componentes incluidos salvo los embeddings
locales.

### Los archivos `.env` solo se leen cuando se pide {#env-files-are-read-only-when-asked}

`load_config` y `load_config_async` ya no buscan un archivo `.env` de forma
implícita. Pasa el archivo o pide la búsqueda:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), load_env=True)
config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
```

Sin ninguna de las dos opciones, la clave de la API ya debe estar en el
entorno.

### Los exportadores reciben el registro y su destino {#exporters-take-the-record-and-their-destination}

`AsyncExporter.export(data, destination)` se sustituye por un ciclo de vida. El
pipeline llama a `open()` antes de la primera solicitud de listado, a
`write(record, entities)` para cada registro procesado, incluido uno sin
entidades, a `flush()` después de cada página y a `aclose()` cuando termina la
ejecución, termine como termine. Un exportador recibe su destino al
construirse, así que el argumento `destination=` del pipeline ha desaparecido:

```python
from sci_etl_core import AsyncCsvExporter, AsyncETLPipeline

pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager,
)
```

`AsyncCsvUpsertExporter` se ha eliminado. Su sustituto, `AsyncCsvExporter`, no
fusiona filas: escribe una fila por entidad con el `record_id` del artículo
del que procede, guarda las demás claves en una columna `extra` y escribe los
valores sin cambios, de modo que un valor nunca se recorta, se convierte ni se
pierde, y dos artículos que informan sobre un mismo objeto dan dos filas.
Fusiona en el posprocesamiento, donde la elección es explícita:

```python
import pandas as pd

from sci_etl_core.processors import DeduplicationStep, DefaultKeyNormalizer, NormalizationStep, ProcessorChain

raw = pd.read_csv("results.csv", dtype={"record_id": str, "name": str})
one_row_per_name = ProcessorChain(
    [NormalizationStep("name", DefaultKeyNormalizer()), DeduplicationStep("_norm_key")]
).process(raw)
```

El archivo CSV se escribe cuando termina la ejecución; durante la ejecución,
las páginas van a `results.csv.journal`, que la siguiente ejecución reproduce
si una ejecución se colgó. Añade `*.journal` a `.gitignore` junto a tu salida.
La cabecera del nuevo archivo es `record_id`, tus columnas y `extra`, así que
empieza un archivo nuevo en lugar de apuntar el exportador a uno escrito por
`AsyncCsvUpsertExporter`; el exportador rechaza un archivo con otra cabecera.
`AsyncJsonlExporter` escribe en su lugar una línea JSON por registro.

Un exportador personalizado implementa `write` y, si usa búfer, fija
`durable_writes = False` e implementa `flush`:

```python
from sci_etl_core import AsyncExporter


class DatabaseExporter(AsyncExporter):
    def __init__(self, database):
        self.database = database

    async def write(self, record, entities):
        await self.database.replace_rows(record.record_id, list(entities))
```

`write` debe ser idempotente, ya que un fallo puede repetir un registro, y un
registro sin entidades debe borrar lo que guardó una escritura anterior. Un
registro se marca como procesado solo cuando sus entidades son duraderas: justo
después de `write`, o después del `flush` de la página cuando `durable_writes`
es `False`. Un fallo de `write` hace fallar el registro y cuenta un intento, un
fallo de `flush` deja sin resolver los registros escritos de la página sin
contar ningún intento, y un fallo de `open` aborta la ejecución antes de
cualquier solicitud.
[Semántica de ejecución](https://xueromll.github.io/sci-etl-core/latest/guide/run-semantics/)
los numera de R20 a R23.

`AsyncSqlTableExporter` y `AsyncPlotly3DExporter` se han eliminado; usa
`SqlTableSink` y `Plotly3DSink` de `sci_etl_core.processors.sinks`, como
muestra [Sumideros de tablas](#table-sinks). `ScatterPlotConfig` se importa
desde `sci_etl_core.processors`.

### Los extractores de entidades son tipados y usan el registro {#entity-extractors-are-typed-and-record-aware}

`AsyncEntityExtractor` es genérico en su tipo de entidad, y el pipeline llama
a `extract_record(record, text)`, cuya implementación por defecto llama a
`extract(text)`. Un extractor que solo sobrescribe `extract` no necesita
cambios. Un envoltorio alrededor de otro extractor debería delegar también
`extract_record`, para seguir funcionando alrededor de un extractor que
necesita el registro, como `AsyncLLMClaimExtractor`:

```python
from sci_etl_core import AsyncEntityExtractor


class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(self, inner, validator):
        self.inner = inner
        self.validator = validator
        self.requires_record = inner.requires_record

    async def extract(self, text):
        return [entity for entity in await self.inner.extract(text) if self.validator.is_valid(entity)]

    async def extract_record(self, record, text):
        entities = await self.inner.extract_record(record, text)
        return [entity for entity in entities if self.validator.is_valid(entity)]
```

Ese envoltorio normalmente ya no es necesario: `AsyncLLMEntityExtractor`
acepta un `validator`, registra cada rechazo con sus motivos y puede conservar
las entidades rechazadas en un almacén de rechazos. Todos los argumentos
después de `system_prompt` son ahora de solo nombre.

Para validar entidades contra un modelo de Pydantic y recibir instancias del
modelo, pasa `schema=`; consulta
[Entidades tipadas y validación](https://xueromll.github.io/sci-etl-core/latest/guide/typed-entities/).
Un `AsyncLLMClient` personalizado que envuelve a otro debería reenviar
`complete_structured` y aceptar `schema=` en `invalidate`.

### Los validadores explican el motivo {#validators-say-why}

`RecordValidator.validate(entity)` devuelve un `ValidationResult` de
`Violation`. Un validador que solo implementa `is_valid` sigue funcionando.
Uno que ya calcula un motivo, como un método `rejection_reason`, puede
sobrescribir `validate` en su lugar, y el motivo llega al registro y al almacén
de rechazos:

```python
from sci_etl_core.processors import RecordValidator, ValidationResult, Violation


class RangeValidator(RecordValidator):
    def is_valid(self, record):
        return self.validate(record).ok

    def validate(self, record):
        radius = record.get("radius_kpc")
        if radius is not None and not 0.1 <= float(radius) <= 20.0:
            violation = Violation(code="out-of-range", field="radius_kpc", severity="error", message=f"radius {radius} kpc")
            return ValidationResult(violations=(violation,))
        return ValidationResult()
```

### El registro pasa por el módulo `logging` {#logging-goes-through-the-logging-module}

Se han eliminado todos los argumentos `logger=`: de `AsyncETLPipeline`,
`ETLPipeline`, los cuatro extractores, `AsyncLLMEntityExtractor`,
`CachingLLMClient`, `AsyncCompositeIngestor`, `AsyncHybridSearcher` y
`ShutdownSignal`. Se han eliminado `configure_logging` y
`sci_etl_core.log_utils`, y también `AsyncETLPipeline.log`. Cada módulo
registra con su propio nombre por debajo del logger `sci_etl_core`, así que
configura el registro en la aplicación:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler("output/pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
```

Los mensajes conservan su redacción. `CachingLLMClient` aceptaba `logger` como
cuarto argumento posicional; una llamada que lo pasaba por posición ahora falla
con un `TypeError`.

### Nombres eliminados {#removed-names}

Se han eliminado las obsolescencias de la 0.5: los contratos bloqueantes
`Extractor`, `StateManager`, `Exporter`, `LLMClient`, `RelevanceFilter` y
`EntityExtractor`; sus adaptadores `SyncExtractorAdapter`,
`SyncRelevanceFilterAdapter`, `SyncEntityExtractorAdapter`,
`SyncExporterAdapter`, `SyncStateManagerAdapter` y `SyncLLMClientAdapter`;
`LegacyExtractorAdapter`; `AsyncExporter.export` y el argumento `destination`;
`AsyncCsvUpsertExporter`, `AsyncSqlTableExporter` y `AsyncPlotly3DExporter`; y
`configure_logging`. Implementa los contratos asíncronos, ejecutando dentro de
ellos el trabajo bloqueante con `asyncio.to_thread`. `ETLPipeline` se mantiene
y ejecuta el pipeline asíncrono desde código bloqueante como antes.

Desde la 0.6, un nombre obsoleto sigue funcionando durante al menos dos
versiones menores antes de eliminarse.

## Actualizar a la 0.5.1 {#upgrading-to-051}

La 0.5.1 no rompe ninguna llamada existente, pero tres resultados del LLM que
antes resolvían un registro ahora lo hacen fallar. El registro queda sin
marcar, su intento cuenta para `max_attempts` y la siguiente ejecución lo
reintenta:

- **Una respuesta vacía.** `AsyncOpenAICompatibleClient.complete_json` lanza
  `LLMError` en lugar de devolver `{}`.
- **Una respuesta sin lista de entidades.** `AsyncLLMEntityExtractor.extract`
  lanza `LLMError` cuando la respuesta está vacía, o tiene varias claves y
  ninguna es `result_key`, en lugar de devolver `[]`.
- **Un fallo de relevancia con `default_on_error=False`.**
  `AsyncLLMRelevanceFilter` y `AsyncEmbeddingRelevanceFilter` lanzan una
  excepción en lugar de interpretar el fallo como "irrelevante", lo que marcaba
  el registro como procesado para siempre.

Si tu modelo responde a veces con un objeto vacío, o con la lista de entidades
bajo otra clave, esos registros ahora fallan y entran en cuarentena después de
`max_attempts` ejecuciones. Nombra `result_key` en el prompt. Un
`AsyncLLMClient` personalizado debería lanzar `LLMError` para una respuesta que
no puede leer en lugar de devolver `{}`.

Los registros que las versiones anteriores marcaron como procesados de este
modo siguen marcados; solo una ejecución con un estado nuevo vuelve a ellos.

La caché del LLM también cambia:

- **Cada respuesta guardada en caché falla una vez.** La clave de caché incluye
  ahora el `base_url` del endpoint, la temperatura y el formato de respuesta,
  así que la primera ejecución tras la actualización llama al LLM para cada
  solicitud. Las entradas escritas por versiones anteriores no se vuelven a
  leer nunca; borra el archivo de caché, o llama a `clear()`, para recuperar el
  espacio. Ya no hace falta un nombre de modelo que codifique la temperatura,
  como `"gpt-4o-mini@t0.2"`.
- **Las respuestas rechazadas se eliminan.** `AsyncLLMEntityExtractor` y
  `AsyncLLMRelevanceFilter` llaman a `invalidate` en su cliente cuando
  rechazan una respuesta, y `CachingLLMClient` la borra, de modo que el
  reintento llega al modelo. Un `AsyncLLMResponseCache` personalizado debería
  implementar `delete`. Un cliente personalizado que envuelve a otro debería
  reenviarle `invalidate`.

## Actualizar a la 0.5 {#upgrading-to-05}

La 0.5 cambia cómo paginan los extractores, qué guarda el estado y cómo se
construye el pipeline. Las entidades y los exportadores cambian en la 0.6.
Exige la nueva versión menor y Python 3.11:

```text
sci-etl-core[async,llm,pdf]>=0.5.0,<0.6
```

El estado escrito por la 0.4 no necesita conversión. `AsyncSqliteStateManager`
actualiza su base de datos en su sitio, y `AsyncFileStateManager` lee el
antiguo archivo de metadatos y lo reescribe en el formato nuevo al guardar la
próxima vez. En ambos casos, el desplazamiento guardado se convierte en el
cursor, así que la siguiente ejecución continúa donde se detuvo la anterior.

### Los extractores devuelven páginas analizadas {#extractors-return-parsed-pages}

`search` y `parse_listing` se sustituyen por un único `fetch_page`, que
devuelve un `ListingPage`. Ahora el propio pipeline omite los registros
procesados, así que un extractor devuelve todas las entradas que puede leer.
Una fuente que pagina por desplazamiento implementa también
`cursor_for_offset`, lo que la convierte en un `OffsetListing`.

Antes:

```python
class MyExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return await self._client.get_page(query, start_index, max_results)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        entries = parse(raw_listing)
        return [entry for entry in entries if entry.record_id not in seen_ids], len(entries)
```

Después:

```python
class MyExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = int(cursor or 0)
        entries = parse(await self._client.get_page(query, offset, page_size))
        return ListingPage(
            records=tuple(entries),
            entries=len(entries),
            next_cursor=str(offset + len(entries)) if entries else None,
        )
```

Una fuente con tokens de continuación opacos devuelve el token como
`next_cursor` y omite `cursor_for_offset`. Una fuente que se detiene en su
propio límite de resultados devuelve `truncated=True` y `next_cursor=None` en
la página que lo alcanza. Hasta que se traslade un extractor,
`LegacyExtractorAdapter(MyOldExtractor())` lo ejecuta sin cambios en la 0.5.x,
con un `DeprecationWarning`; la 0.6 elimina el adaptador.

Un envoltorio que reenvía las llamadas a otro extractor, como uno que registra
el progreso, reenvía `fetch_page`, y también `cursor_for_offset` cuando
envuelve un `OffsetListing`:

```python
class LoggingExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return self._inner.cursor_for_offset(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self._log(f"Fetching listing page at cursor {cursor or 'start'}")
        return await self._inner.fetch_page(query, cursor, page_size)
```

`newest_first=True` y un `start_index` mayor que 0 necesitan un `OffsetListing`
y, si no, lanzan `ValueError` antes de cualquier solicitud.
`AsyncArxivExtractor`, `AsyncPubMedExtractor` y
`AsyncSemanticScholarExtractor` son `OffsetListing`. `AsyncOpenAlexExtractor`
pagina ahora con los cursores de OpenAlex, así que llega más allá de los
primeros 10 000 trabajos pero ya no admite `newest_first`; su primera ejecución
con la 0.5 reinicia una vez el listado desde la primera página, porque el
desplazamiento que guardó la 0.4 no es un cursor de OpenAlex.

### Qué guarda el estado {#what-the-state-saves}

`PipelineMetadata.cursor` sustituye a `last_start_index`. El código que lee la
posición guardada lee el cursor, que es un desplazamiento decimal en el caso de
un `OffsetListing`:

```python
metadata = await state.load_metadata()
saved_offset = int(metadata.cursor or 0)
```

Los eventos de progreso incorporan `cursor`. `RunStarted.start_index`,
`PageFetched.offset` y `PageFinished.offset` siguen conteniendo el
desplazamiento del listado para un `OffsetListing` y son `None` para cualquier
otro extractor.

### Los listados con límite vuelven a empezar {#capped-listings-start-over}

PubMed se detiene en 9999 resultados, Semantic Scholar en 1000. En la 0.4, una
ejecución que alcanzaba el límite guardaba el límite como su desplazamiento, y
todas las ejecuciones posteriores terminaban allí de inmediato. En la 0.5, la
página que alcanza el límite termina la ejecución como `"completed"`,
`RunMetrics.listing_truncated` lo indica y el cursor guardado se restablece,
así que la siguiente ejecución vuelve a paginar los resultados accesibles: los
registros procesados se omiten por identificador, así que la nueva pasada
cuesta solicitudes de listado, no llamadas al LLM. Acota la consulta, por
ejemplo por fecha, para evitar la nueva pasada.

### Los registros que siguen fallando entran en cuarentena {#records-that-keep-failing-are-quarantined}

Un registro que falla en 3 ejecuciones, cada vez en una página en la que se
procesó otro registro, se omite por estar en cuarentena a partir de la
siguiente ejecución y se cuenta en `RunMetrics.quarantined`. Los fallos en una
página donde no se procesó nada, como durante una caída o con una clave de API
rechazada, nunca se cuentan. Para mantener el comportamiento de la 0.4, que
reintenta para siempre cada registro fallido:

```python
await pipeline.run(query, page_size=100, total_limit=500, max_attempts=None)
```

Un gestor de estado de terceros sigue funcionando sin cambios: los nuevos
`record_failure` y `failure_counts` tienen implementaciones por defecto que no
registran nada, así que nunca pone registros en cuarentena.

### Argumentos con nombre {#keyword-arguments}

`AsyncETLPipeline` y `ETLPipeline` reciben los cinco colaboradores por posición
o por nombre, y todo lo demás por nombre. `run` recibe `query` y después solo
argumentos con nombre, y `max_records=` ha desaparecido:

```python
pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    exporter,
    state_manager,
    destination="results.csv",
    max_concurrency=4,
)
await pipeline.run("all:galaxy", page_size=50, total_limit=200)
```

`RawRecord`, `PipelineMetadata`, `TokenUsage`, `RunMetrics` y los eventos son
de solo argumentos con nombre, así que `RawRecord("id", "title", "abstract")`
pasa a ser `RawRecord(record_id="id", title="title", abstract="abstract")`.

### Secciones de configuración estrictas {#strict-config-sections}

Una clave que una sección incluida no declara ahora no supera la validación y
se nombra en el `ConfigurationError`, así que una errata como
`search.bm25.titel` o la antigua clave `pipeline.max_records` ya no pasan en
silencio. Renombra `pipeline.max_records` a `total_limit` y
`pipeline.max_workers` a `max_concurrency`. Una aplicación que de momento deba
aceptar claves desconocidas lo desactiva en su clase de configuración, y cada
clave descartada se notifica con un `UserWarning`:

```python
class AppConfig(BaseAppConfig):
    strict_sections = False
```

Las secciones de nivel superior que define la aplicación se conservan como
antes.

### Sumideros de tablas {#table-sinks}

`AsyncSqlTableExporter` y `AsyncPlotly3DExporter` recibían un `DataFrame` y no
podían ejecutarse en el pipeline. Sus sustitutos son sumideros bloqueantes para
la salida del posprocesamiento:

```python
from sci_etl_core.processors.sinks import Plotly3DSink, ScatterPlotConfig, SqlTableSink

catalogue = chain.process(raw_table)
SqlTableSink("sqlite:///catalogue.db", "galaxies", if_exists="replace").write(catalogue)
Plotly3DSink(ScatterPlotConfig("x", "y", "z", color_column="size"), "catalogue.html").write(catalogue)
```

### Obsolescencias sin sustituto antes de la 0.6 {#deprecations-with-no-replacement-before-06}

Estos nombres siguen funcionando en la 0.5.x y emiten un
`PendingDeprecationWarning`, no un `DeprecationWarning`, porque sus sustitutos
llegan en la 0.6 y todavía no hay nada que cambiar: el argumento
`destination`, `AsyncExporter.export` y `AsyncCsvUpsertExporter` (sustituidos
por el ciclo de vida del exportador y `AsyncCsvExporter`), y todos los
argumentos `logger=` y `configure_logging` (sustituidos por el módulo estándar
`logging`). Por eso, una batería de pruebas ejecutada con
`-W error::DeprecationWarning` sigue pasando mientras los usa.

Los contratos bloqueantes y sus `Sync*Adapter`, `LegacyExtractorAdapter` y los
dos exportadores de tablas emiten un `DeprecationWarning`, porque sus
sustitutos ya existen en la 0.5; pasa a los contratos asíncronos, que ya
implementan todos los componentes, a `fetch_page` y a los sumideros de tablas.

`build_retrying_session` se ha eliminado, y el extra `full` ya no instala
`requests`.

## Actualizar a la 0.4 {#upgrading-to-04}

```text
sci-etl-core[async]>=0.4.0,<0.5
```

La 0.4 añade nuevas fuentes, analizadores, caché de respuestas del LLM, apagado
ordenado, eventos de progreso, limitadores de frecuencia y funciones de
búsqueda. Estos cambios afectan al código existente:

- **Ajustes del pipeline renombrados.** `pipeline.max_records` es ahora
  `total_limit` y `pipeline.max_workers` es `max_concurrency`. Las antiguas
  claves YAML y las propiedades `PipelineConfig.max_records` y `max_workers`
  siguen funcionando hasta la 0.5, con un `DeprecationWarning`, y
  `run(max_records=)` queda obsoleto del mismo modo. Renombra ambas claves en tu
  archivo de configuración.
- **Más ajustes del pipeline.** `PipelineConfig` tiene ahora `page_size`,
  `search_delay` y `newest_first`. Una subclase que solo añadía esos campos se
  puede borrar.
- **Validación sin envoltorio.** `AsyncLLMEntityExtractor` acepta
  `validator=`, `logger=` y `label_field=`, y registra cada entidad que
  descarta como `Entity rejected by validation: <label>`. Un extractor que lo
  envolvía solo para aplicar un `RecordValidator` se puede borrar.
- **Componentes desde la configuración.** `AsyncArxivExtractor.from_config`,
  `AsyncOpenAICompatibleClient.from_config` y `AsyncETLPipeline.from_config`
  leen las secciones `http`, `llm` y `pipeline`, `config.http.build_client()`
  sustituye a `build_async_client`, y `config.pipeline.run_arguments()`
  devuelve los argumentos de `run()`, así que ya no hay que copiar los ajustes a
  mano en los constructores.
- **Reanudación con los más recientes primero.** `run(newest_first=True)`
  recoge los envíos nuevos de arXiv sin la nueva pasada completa que cuesta
  `start_index=0`, y guarda la cabecera del listado en el archivo de metadatos
  junto a `last_start_index`. `start_index` no se puede combinar con ello.
- **Gráficos.** `ScatterPlotConfig` acepta `hover_data_columns`,
  `hover_template`, `color_continuous_scale` y `color_range`, que cubren el
  texto emergente personalizado y los intervalos de colores fijos que antes
  requerían construir la figura a mano.
- **Restricción de valores y diseño de la tabla.** `ValueClipStep` restringe
  columnas durante el posprocesamiento, y `TableLayoutStep` ordena las filas y
  las columnas, en lugar de procesadores propios del proyecto que hacían una u
  otra cosa.
- **Búsqueda a partir de la memoria que ya tienes.** Un proyecto que guardaba
  fragmentos en un `AsyncSqliteEmbeddingStore` puede construir a partir de
  ellos un índice de texto con `backfill_text_index` en lugar de volver a
  descargar todos los artículos.
- **Extractos para los resultados semánticos.** Un `FusedHit` encontrado solo
  por la rama semántica lleva ahora un extracto de su mejor fragmento,
  donde antes tenía un `snippet` vacío. Una interfaz que mostraba el resumen
  siempre que `snippet` estaba vacío debería comprobar `lexical_rank is None`
  en su lugar.
- **Ayudante de `requests` obsoleto.** `build_retrying_session` emite una
  advertencia y se eliminará en la 0.5, junto con `requests` en el extra
  `full`.

## Actualizar a la 0.3 {#upgrading-to-03}

```text
sci-etl-core[async]>=0.3.0,<0.4
```

La 0.3 añade la búsqueda local y los grafos de descubrimiento. Estos cambios
afectan al código existente:

- **Los registros de arXiv llevan metadatos.** `RawRecord.metadata` contiene
  ahora `categories`, `authors`, `published` y `year` en lugar de quedarse
  vacío. Tu propio código que lee registros, incluidas las pruebas que
  comparan `metadata == {}`, ve las nuevas claves. Los metadatos guardados con
  los fragmentos de embeddings no cambian.
- **`memory_ingestor` acepta cualquier `MemoryIngestor`.** Un
  `AsyncChunkIngestor` funciona exactamente igual que antes. Una anotación de
  tipo de tu código que nombre `AsyncChunkIngestor` para este argumento puede
  ampliarse a `MemoryIngestor`.
- **La búsqueda es opcional.** No cambia nada en un pipeline que no pasa ningún
  índice de texto. Para añadir uno, pasa un `AsyncSearchIndexer`, o un
  `AsyncCompositeIngestor` con un ingestor de fragmentos en primer lugar, como
  muestra
  [Búsqueda y descubrimiento locales](https://xueromll.github.io/sci-etl-core/latest/guide/search/).
  Su `AsyncSqliteFts5Store` va en `closeables` como cualquier otro almacén
  SQLite.
- **El estado en SQLite es más seguro ante la cancelación.**
  `AsyncSqliteStateManager` ya no deja que el hilo de trabajo de una operación
  cancelada se solape con la siguiente operación. `AsyncFileStateManager` no
  cambia.

¿Tienes preguntas o has encontrado una aspereza en la actualización? Abre una
[incidencia](https://github.com/xueromll/sci-etl-core/blob/master/.github/ISSUE_TEMPLATE/bug_report.md):
estaremos encantados de ayudarte.
