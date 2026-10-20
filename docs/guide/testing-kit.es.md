# Probar tus componentes

`sci_etl_core.testing` contiene baterías de pruebas de contrato: clases de
prueba de pytest que comprueban el comportamiento de un componente según el
contrato de su clase base. Hereda la batería de tu componente, añade una
fixture que lo construya, y pytest ejecuta cada prueba de la batería contra tu
implementación. Las implementaciones incluidas pasan las mismas baterías.

| Batería | Comprueba | Implementaciones incluidas contra las que se ejecuta |
|---------|-----------|------------------------------------------------------|
| `ExtractorContract` | `AsyncExtractor` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor` |
| `StateManagerContract` | `AsyncStateManager` | `AsyncFileStateManager`, `AsyncSqliteStateManager` |
| `ExporterContract` | `AsyncExporter` | `AsyncJsonlExporter`, `AsyncCsvExporter`, `AsyncClaimStoreExporter` |
| `EmbeddingStoreContract` | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`, `AsyncSqliteEmbeddingStore` |

## Instalación {#installing}

Las baterías necesitan pytest, que instala el extra `testing`:

```bash
pip install "sci-etl-core[testing]"
```

Ningún otro módulo de la biblioteca importa pytest. Las pruebas son funciones
normales que ejecutan cada escenario con `asyncio.run`, así que no necesitas
pytest-asyncio.

## Escribir una prueba de contrato {#writing-a-contract-test}

Hereda la batería en un módulo de pruebas, con un nombre que pytest recoja, y
dale la fixture que la batería pide. Aquí un gestor de estado que guarda su
estado en memoria pasa `StateManagerContract`:

```python
import dataclasses

import pytest

from sci_etl_core import AsyncStateManager, PipelineMetadata
from sci_etl_core.testing import StateManagerContract


class MemoryStateManager(AsyncStateManager):
    def __init__(self) -> None:
        self._processed: set[str] = set()
        self._metadata = PipelineMetadata()

    async def load_processed_ids(self) -> set[str]:
        return set(self._processed)

    async def mark_processed(self, record_id: str) -> None:
        self._processed.add(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return dataclasses.replace(self._metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        self._metadata = dataclasses.replace(metadata)


class TestMemoryStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self):
        manager = MemoryStateManager()
        return lambda: manager
```

Ahora `python -m pytest` ejecuta cada prueba de la batería contra
`MemoryStateManager`. La clase de la batería no se recoge por sí misma, porque
su nombre no empieza por `Test`.

La fixture devuelve una fábrica: un invocable sin argumentos que devuelve en
cada llamada una instancia nueva sobre el mismo almacenamiento, como lo abre
cada ejecución de un pipeline. La batería la llama más de una vez en una
prueba para comprobar que lo que guardó una instancia lo carga la siguiente.
Un componente que guarda su estado en memoria, como el de arriba, devuelve
siempre la misma instancia. El almacenamiento empieza vacío en cada prueba,
así que créalo a partir de `tmp_path` o dentro de la fixture. La batería llama
a la fábrica dentro de un bucle de eventos en marcha y termina cada instancia
como termina una ejecución: vuelca el estado de un gestor de estado y lo
cierra con `aclose()` cuando lo tiene, y cierra un exportador o un almacén
vectorial.

## Fixtures {#fixtures}

| Batería | Fixtures obligatorias | Fixtures opcionales |
|---------|-----------------------|---------------------|
| `ExtractorContract` | `make_extractor` | `make_unavailable_extractor` |
| `StateManagerContract` | `make_state_manager` | `write_newer_schema` |
| `ExporterContract` | `make_exporter`, `read_exported` | `make_entities`, `write_newer_schema` |
| `EmbeddingStoreContract` | `make_store` | `write_newer_schema` |

- **`make_extractor`, `make_state_manager`, `make_exporter` y `make_store`**
  devuelven la fábrica descrita arriba.
- **`read_exported`** devuelve un invocable asíncrono que recibe un id de
  registro y devuelve las entidades que el destino guarda para ese registro, o
  una secuencia vacía. La batería compara dos lecturas, así que devuelve una
  forma que sea igual cuando el contenido es el mismo.
- **`make_entities`** devuelve un invocable que construye `count` entidades
  distintas para un registro. El valor por defecto construye diccionarios con
  las claves `name` y `value`; sobrescríbelo cuando tu exportador reciba otras
  entidades, como afirmaciones.
- **`write_newer_schema`** devuelve un invocable que escribe, en el
  almacenamiento que abre la fábrica, un archivo o una base de datos con una
  versión de esquema más nueva que la que admite tu componente. La batería lo
  llama antes de crear una instancia y espera un `SciEtlError`. El valor por
  defecto devuelve `None`.
- **`make_unavailable_extractor`** devuelve una fábrica de un extractor cuya
  fuente responde a cada petición con un fallo del servidor, como el estado
  `503`, sin esperar entre reintentos. La batería espera `UpstreamError` en
  lugar de una página vacía. El valor por defecto devuelve `None`.

La misma batería de gestores de estado, ejecutada contra el gestor de estado
SQLite incluido, comprueba también que se rechaza una base de datos de una
versión más nueva:

```python
import sqlite3
from contextlib import closing

import pytest

from sci_etl_core import AsyncSqliteStateManager
from sci_etl_core.testing import StateManagerContract


class TestSqliteStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: AsyncSqliteStateManager(tmp_path / "state.db")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        def write():
            with closing(sqlite3.connect(tmp_path / "state.db")) as connection:
                connection.execute("PRAGMA user_version = 99")

        return write
```

Un exportador necesita además `read_exported`, que vuelve a leer su destino:

```python
import pytest

from sci_etl_core.exporters import AsyncJsonlExporter, read_jsonl_export
from sci_etl_core.testing import ExporterContract


class TestJsonlExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncJsonlExporter(tmp_path / "out.jsonl", fsync=False)

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            return read_jsonl_export(tmp_path / "out.jsonl").get(record_id, [])

        return read
```

## Probar un extractor sin red {#testing-an-extractor-offline}

La batería de extractores nunca usa la red. Sirve el listado desde un stub,
como un `httpx.AsyncClient` construido sobre `httpx.MockTransport`, y haz que
responda siempre igual a la misma petición. El listado debe tener al menos dos
páginas para la consulta de la batería y terminar en `max_pages` páginas como
mucho. Ajusta estos atributos de clase en tu subclase según tu fuente:

| Atributo | Valor por defecto | Significado |
|----------|-------------------|-------------|
| `query` | `"contract"` | La consulta que lista cada prueba |
| `page_size` | `2` | El tamaño de página que pide cada prueba |
| `max_pages` | `50` | El máximo de páginas en que debe terminar el listado |

## Capacidades opcionales y omisiones {#optional-capabilities-and-skips}

Una prueba que comprueba una capacidad opcional se omite, con el motivo,
cuando tu componente no la tiene:

- **Gestores de estado:** los intentos fallidos, cuando `record_failure`
  mantiene el valor por defecto que no registra nada; `forget`, cuando el
  gestor de estado no es `Forgetting`; la reutilización tras `aclose()`,
  cuando no tiene `aclose`.
- **Exportadores:** leer una escritura antes de `flush`, cuando
  `durable_writes` es `False`.
- **Almacenes vectoriales:** `iter_records`, cuando el almacén mantiene el
  valor por defecto que lanza `NotImplementedError`.
- **Extractores:** la prueba de desplazamientos, cuando el extractor no es un
  `OffsetListing`; la prueba de fuente no disponible, cuando
  `make_unavailable_extractor` devuelve `None`.
- **Gestores de estado, exportadores y almacenes vectoriales:** la prueba de
  versión de esquema, cuando `write_newer_schema` devuelve `None`.

## Qué comprueban las baterías {#what-the-suites-check}

- **`ExtractorContract`:** la primera página es un `ListingPage` bien formado
  con registros y un cursor siguiente; un cursor siguiente devuelve otra vez la
  misma página, también desde un extractor nuevo, como la pide una ejecución
  reanudada; seguir los cursores siguientes termina el listado, y una página
  truncada no tiene cursor siguiente; para un `OffsetListing`, el
  desplazamiento 0 es la primera página y el número de entradas de la primera
  página es el desplazamiento de la segunda; `fetch_full_text` devuelve una
  cadena; una fuente inalcanzable lanza `UpstreamError`.
- **`StateManagerContract`:** un almacenamiento nuevo está vacío; los ids
  procesados, los metadatos guardados y los intentos fallidos llegan a la
  siguiente instancia; se conservan todas las marcas concurrentes;
  `save_metadata` registra la hora de la ejecución; `mark_processed` borra los
  intentos de un registro; `forget` borra marcas e intentos y conserva el
  cursor; se rechaza un estado con una versión de esquema más nueva; un gestor
  de estado vuelve a funcionar tras `aclose()`.
- **`ExporterContract`:** una ejecución exporta las entidades de cada
  registro; repetir una escritura, de forma concurrente, en la misma ejecución
  o en una posterior, deja lo que dejó una sola escritura; un registro escrito
  sin entidades no guarda ninguna; una ejecución sin escrituras termina bien;
  un exportador vuelve a ejecutarse tras `aclose()`; con
  `durable_writes = True`, una escritura se puede leer antes de `flush`; se
  rechaza un destino con una versión de esquema más nueva.
- **`EmbeddingStoreContract`:** un almacén nuevo está vacío; un fragmento
  añadido de nuevo con su id de registro e índice sustituye al anterior; los
  fragmentos llegan a la siguiente instancia; los resultados llegan del mejor
  al peor por similitud del coseno y respetan `top_k`, `min_score` y
  `exclude_record_id`; un vector con NaN nunca coincide; `delete_record` y
  `replace_record` no dejan ningún fragmento antiguo del registro;
  `iter_records` produce los pasajes en orden; un almacén vuelve a funcionar
  tras `aclose()`; se rechaza un almacenamiento con una versión de esquema más
  nueva.

Las baterías comprueban el comportamiento solo a través de los métodos
públicos. La
[tabla de contratos](../project/contributing.md#adding-a-new-component) indica
lo que debe hacer cada componente, y la
[referencia de la API de pruebas](../reference/testing.md) documenta cada
batería.
