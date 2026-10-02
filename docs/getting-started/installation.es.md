# Instalación

Se requiere Python 3.11 o posterior.

```bash
pip install "sci-etl-core[async,arxiv,llm,pdf]"   # todo lo que usa el inicio rápido
pip install "sci-etl-core[full]"                  # todos los componentes incluidos salvo los embeddings locales
```

Desde un clon del repositorio:

```bash
pip install -e ".[full]"
```

La instalación base solo requiere Pydantic. Incluye los dos pipelines, el
apagado ordenado, los eventos de progreso y las métricas de ejecución, los
contratos de los componentes, los modelos de configuración, los backends de
estado, la caché de respuestas del LLM, los exportadores CSV y JSON Lines, las
afirmaciones y su procedencia, los validadores de registros, el análisis de
LaTeX, la fragmentación de texto, la búsqueda booleana de texto, la fusión de
clasificaciones y los grafos de descubrimiento. Un componente que necesita otro
paquete lo importa cuando importas el componente, así que añade los extras de
los componentes que uses:

| Extra | Añade | Necesario para |
|-------|-------|----------------|
| `config` | `pyyaml`, `python-dotenv` | `load_config`, `load_config_async`, `load_yaml` |
| `async` | `httpx`, `aiolimiter` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor`, `build_async_client`, `AioLimiterRateLimiter` |
| `arxiv` | `beautifulsoup4`, `lxml` | `AsyncArxivExtractor`, que también necesita `async` |
| `xml` | `lxml` | `JatsXmlParser`, `DocxParser` y `AsyncPubMedExtractor`, que también necesita `async` |
| `html` | `beautifulsoup4` | `HtmlTextParser`, que `AsyncLLMEntityExtractor` usa por defecto para el texto completo que empieza con marcado |
| `processors` | `pandas`, `numpy` | todos los pasos de `sci_etl_core.processors` salvo los validadores, y los sumideros de tablas |
| `llm` | `openai`, `tiktoken` | `AsyncOpenAICompatibleClient`, truncado por tokens |
| `pdf` | `pdfplumber` | `PdfPlumberParser` |
| `sql` | `sqlalchemy` | `SqlTableSink`, que también necesita `processors` |
| `viz` | `plotly` | `Plotly3DSink`, que también necesita `processors` |
| `cluster` | `scikit-learn`, `numpy` | `ClusteringStep`, que también necesita `processors` |
| `embeddings` | `numpy`, `openai` | `AsyncOpenAIEmbedder`, los almacenes vectoriales, `AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `numpy`, `sentence-transformers` | `AsyncSentenceTransformerEmbedder` |
| `search` | nada | nada adicional: `sci_etl_core.search` solo necesita la biblioteca estándar, así que este extra solo deja constancia de por qué está instalado el paquete |
| `full` | todos los paquetes anteriores salvo `sentence-transformers` | todos los componentes incluidos salvo los embeddings locales |
| `dev` | pytest y plugins, `hypothesis` | ejecutar la batería de pruebas |
| `lint` | `ruff`, `mypy`, stubs de tipos | revisar el estilo y los tipos del código fuente |
| `docs` | MkDocs, Material for MkDocs, mkdocstrings, mkdocs-click, mike, mkdocs-static-i18n, `ruff` | construir este sitio de documentación |

Importar un componente cuyo extra falta lanza `ModuleNotFoundError` con el
nombre del paquete que hay que instalar.

!!! tip "¿Solo quieres ejecutar un pipeline?"
    `pip install sci-etl-cli` instala el [comando `sci-etl`](../cli/index.md),
    que ejecuta un proyecto de extracción de arXiv a partir de un archivo YAML
    sin código de conexión.
