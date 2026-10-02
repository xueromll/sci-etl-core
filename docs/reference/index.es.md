# Referencia de la API

Estas páginas se generan a partir de las docstrings y las anotaciones de tipo
del código fuente, por lo que las descripciones de clases y funciones están en
inglés. Cada página documenta los módulos que definen los nombres; impórtalos
desde el paquete indicado al principio de la página, no desde el módulo que los
define, ya que la organización de los módulos dentro de un paquete puede cambiar
entre versiones.

| Página | Paquete | Contenido |
|--------|---------|-----------|
| [Pipelines](pipelines.md) | `sci_etl_core` | `AsyncETLPipeline`, `ETLPipeline`, ingesta en memoria, `ShutdownSignal`, eventos de progreso y `RunMetrics` |
| [Configuración](configuration.md) | `sci_etl_core` | `BaseAppConfig` y sus secciones, `load_config`, `load_config_async` |
| [Modelos y excepciones](models.md) | `sci_etl_core` | `RawRecord`, `TokenUsage`, la jerarquía de `SciEtlError`, el modelo de lectura del descubrimiento |
| [Extractores](extractors.md) | `sci_etl_core.extractors` | `AsyncExtractor`, los extractores de arXiv, PubMed, Semantic Scholar y OpenAlex |
| [Analizadores](parsers.md) | `sci_etl_core.parsers` | analizadores de PDF, LaTeX, HTML, DOCX y JATS XML, recorte de referencias |
| [LLM](llm.md) | `sci_etl_core.llm` | clientes de LLM, caché de respuestas, filtros de relevancia, extractores de entidades y esquemas tipados |
| [Embeddings](embeddings.md) | `sci_etl_core.embeddings` | generadores de embeddings, fragmentación, almacenes vectoriales, búsqueda por similitud |
| [Búsqueda](search.md) | `sci_etl_core.search` | lenguaje de consultas, almacenes de texto, fusión, búsqueda híbrida, grafos de descubrimiento |
| [Exportadores](exporters.md) | `sci_etl_core.exporters` | el ciclo de vida del exportador, exportadores CSV y JSON Lines |
| [Afirmaciones](claims.md) | `sci_etl_core.claims` | afirmaciones, fragmentos de evidencia, sellos, almacenes de afirmaciones y de rechazos, el extractor y el exportador de afirmaciones (provisional) |
| [Procesadores](processors.md) | `sci_etl_core.processors` | pasos sobre DataFrames, normalizadores de claves, validadores de registros y sus infracciones, sumideros de tablas |
| [Estado](state.md) | `sci_etl_core.state` | gestores de estado en archivos y en SQLite |
| [Utilidades](utilities.md) | módulo que lo define | clientes HTTP, limitadores de frecuencia, incluidos los límites por host |

Para ver cómo encajan las piezas, consulta
[Arquitectura](../guide/architecture.md).
