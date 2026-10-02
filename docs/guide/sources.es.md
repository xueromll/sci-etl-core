# Fuentes compatibles

Cada fuente tiene su propio protocolo, modelo de paginación, esquema de
identificadores y formatos de texto completo, así que cada una tiene su propio
`AsyncExtractor` en lugar de un único extractor con opciones para cada fuente.

| Fuente | Extractor | Identificador del registro | Paginación | Texto completo |
|--------|-----------|----------------------------|------------|----------------|
| arXiv | `AsyncArxivExtractor` | identificador de arXiv con versión | desplazamientos | fuente LaTeX, luego PDF, luego resumen |
| PubMed | `AsyncPubMedExtractor` | PMID | desplazamientos, primeros 9999 resultados | JATS de PubMed Central cuando el artículo tiene identificador PMC; si no, el resumen |
| Semantic Scholar | `AsyncSemanticScholarExtractor` | identificador del artículo | desplazamientos, primeros 1000 resultados | PDF de acceso abierto con un `pdf_parser`; si no, el resumen |
| OpenAlex | `AsyncOpenAlexExtractor` | identificador del trabajo, como `W2741809807` | cursores de OpenAlex, sin límite | PDF de acceso abierto con un `pdf_parser`; si no, el resumen |
| bioRxiv, ChemRxiv | No incluido | | | Adapta `AsyncArxivExtractor` |
| Crossref | No incluido | | | Implementa tu propio `AsyncExtractor` |

Un extractor que pagina por desplazamiento es un `OffsetListing`, algo que
necesitan las ejecuciones `newest_first` y `run(start_index=)` mayor que 0.
Cuando una fuente se detiene en su propio límite de resultados, su extractor
marca como `truncated` la página que alcanza el límite: la ejecución termina y
la siguiente vuelve a paginar los resultados accesibles en lugar de detenerse
en el límite. Los registros procesados se omiten por identificador, así que esa
nueva pasada cuesta solicitudes de listado, no llamadas al LLM. Para evitarla,
acota la consulta, por ejemplo por intervalo de fechas.
[Semántica de ejecución](run-semantics.md#capped-listings) tiene los detalles.

Los extractores incluidos comparten el comportamiento de reintentos descrito
en [Reintentos](retries.md) y aceptan un `rate_limiter`
([Limitación de frecuencia](rate-limiting.md)). Cada uno acepta también
`max_download_bytes`, que limita cada cuerpo de respuesta después de
decodificarlo: una página de listado demasiado grande lanza `ExtractionError`,
y una descarga de texto completo demasiado grande se registra y se omite.
`LatexTarballParser(max_tex_bytes=)` limita del mismo modo el TeX
descomprimido de un e-print de arXiv. Cada uno rellena `RawRecord.metadata`
con `authors` y `categories`, y con `published` y `year` cuando la fuente tiene
fecha, para que los filtros y las facetas de búsqueda funcionen igual en todas
las fuentes. Las fuentes distintas de arXiv guardan además ahí `pdf_url` o
`pmcid`, que lee `fetch_full_text`.

## PubMed {#pubmed}

```python
from sci_etl_core import AsyncPubMedExtractor
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncPubMedExtractor(
    client,
    api_key=ncbi_api_key,
    tool="my-project",
    email="you@example.org",
    rate_limiter=build_rate_limiter(max_rate=9, time_period=1.0),
)
await pipeline.run("dark matter[tiab] AND 2020:2026[dp]", total_limit=200, newest_first=True)
```

La consulta usa la sintaxis de búsqueda de PubMed. Los resultados van de más
recientes a más antiguos (`sort="pub_date"`), así que encaja
`newest_first=True`. Cada página de listado cuesta dos solicitudes, y NCBI
permite 3 solicitudes por segundo sin clave de API y 10 con ella, así que lee
la clave del entorno y fija un limitador por debajo de eso. E-utilities pagina
los primeros 9999 resultados de una búsqueda, incluso con su servidor de
historial, así que la página que los alcanza queda como `truncated`. Los
metadatos añaden `journal`, y `doi` y `pmcid` cuando se conocen; `categories`
son los encabezados MeSH.

## Semantic Scholar {#semantic-scholar}

```python
from sci_etl_core import AsyncSemanticScholarExtractor
from sci_etl_core.parsers import PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncSemanticScholarExtractor(
    client,
    PdfPlumberParser(),
    api_key=semantic_scholar_key,
    year="2020-",
    fields_of_study="Physics",
    rate_limiter=build_rate_limiter(max_rate=1, time_period=1.0),
)
```

La búsqueda por relevancia solo devuelve sus primeros 1000 resultados y no
está ordenada por fecha, así que ejecútala sin `newest_first`; la página que
alcanza el resultado número 1000 queda como `truncated`. Los metadatos añaden
`venue`, y `doi`, `arxiv_id` y `pmid` cuando se conocen.

## OpenAlex {#openalex}

```python
from sci_etl_core import AsyncOpenAlexExtractor

extractor = AsyncOpenAlexExtractor(
    client,
    filter="type:article,from_publication_date:2020-01-01",
    mailto="you@example.org",
)
await pipeline.run("ultra-diffuse galaxies", total_limit=500)
```

Por defecto, los resultados van de más recientes a más antiguos
(`sort="publication_date:desc"`). La paginación usa los cursores de OpenAlex,
así que un listado no se limita a sus primeros 10 000 resultados, pero el
extractor no es un `OffsetListing` y no admite ejecuciones `newest_first`.
Cuando una ejecución llega al final del listado, la siguiente vuelve a empezar
desde la primera página y omite por identificador los trabajos procesados. Un
cursor que OpenAlex rechaza reinicia el listado una vez. `mailto` te une al
grupo de uso cortés (polite pool) de OpenAlex. Los resúmenes se reconstruyen a
partir del índice invertido de OpenAlex. Los metadatos añaden `doi`, `venue` y
`references`, los identificadores de los trabajos que cita un artículo.

## Formatos de documento {#document-formats}

Además de los analizadores de PDF, LaTeX y HTML que usan los extractores, dos
analizadores leen formatos que puedes obtener de otras fuentes:

- **`DocxParser`** lee archivos `.docx` de Word con la biblioteca estándar y
  `lxml`: los párrafos en orden, las tablas como filas separadas por
  tabuladores y, con `include_notes=True`, las notas al pie y las notas
  finales.
- **`JatsXmlParser`** lee JATS XML, el formato de PubMed Central y de muchas
  editoriales. `extract_text` devuelve el título, el resumen y el cuerpo sin la
  lista de referencias, y `parse_article` devuelve un `JatsArticle` con
  secciones, autores, palabras clave, revista, fecha de publicación,
  identificadores y referencias.

```python
from sci_etl_core.parsers import JatsXmlParser

article = JatsXmlParser().parse_article(xml_bytes)
print(article.title, article.doi, [section.title for section in article.sections])
```

Ambos analizan el XML sin resolver entidades ni descargar DTD, y lanzan
`ParsingError` para los bytes que no pueden leer.

## Escribir un extractor {#writing-an-extractor}

El pipeline funciona con cualquier clase que implemente este contrato:

```python
from sci_etl_core import AsyncExtractor, ListingPage
from sci_etl_core.models import RawRecord


class MySourceExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...
```

- **`fetch_page`** obtiene y analiza una página. `cursor=None` es la primera
  página; cualquier otro cursor es un `next_cursor` que devolvió una página
  anterior, posiblemente en una ejecución anterior. Devuelve un `ListingPage`
  con todos los registros que pudo leer, el número de entradas de la página,
  contando las que no pudo leer, y el siguiente cursor, o `None` en la última
  página. El propio pipeline omite los registros procesados. Una fuente que se
  detuvo en su propio límite de resultados devuelve `truncated=True`.
- Errores: si no se puede contactar con la fuente, lanza `UpstreamError` en
  lugar de devolver una página vacía; si rechaza la solicitud directamente,
  lanza `ExtractionError`; si la carga útil no se puede leer, lanza
  `MalformedResponseError`. Cada uno aborta la ejecución. Si la fuente ya no
  acepta un cursor, lanza `StaleCursorError`, y la ejecución reinicia una vez
  el listado desde la primera página.
- **`cursor_for_offset`** es solo para una fuente que pagina por
  desplazamiento. Convierte el extractor en un `OffsetListing`; omítelo cuando
  los cursores sean tokens opacos.
- **`fetch_full_text`** devuelve el mejor texto disponible para un registro.

El contrato completo de cada tipo de componente se detalla en
[Añadir un componente nuevo](../project/contributing.md#adding-a-new-component),
y la [referencia de la API de extractores](../reference/extractors.md)
documenta las clases base.
