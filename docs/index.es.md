# sci-etl-core

`sci-etl-core` es una biblioteca de Python para convertir artículos
científicos de cualquier campo de la ciencia en datos estructurados y
consultables. Obtiene artículos de arXiv, PubMed, OpenAlex y Semantic Scholar,
lee su texto completo, extrae con un LLM los valores que pidas y mantiene los
artículos consultables en tu propio equipo.

udg-catalogue muestra el resultado. Criba artículos de astrofísica en arXiv,
extrae mediciones de galaxias ultradifusas y publica un catálogo con
correspondencias cruzadas de 1927 objetos, con búsqueda por palabras clave y
semántica sobre los artículos en los que se basa. `sci-etl-core` aporta la
descarga, el análisis, la extracción, la caché, el estado reanudable y la
búsqueda, mientras que udg-catalogue añade la astronomía: prompts, reglas de
validación, correspondencia por posición en el cielo y el panel de control.

Nada en la biblioteca está ligado a la astronomía. El conocimiento del campo
vive en tus prompts, validadores y normalizadores, así que los mismos bloques
de construcción sirven para cualquier campo de la ciencia.

<div class="grid cards" markdown>

- **Ejecútalo desde YAML**

    ---

    Inicializa, valida, busca y ejecuta proyectos de extracción sin escribir
    código de conexión.

    [sci-etl-cli](cli/index.md)

- **Mira un proyecto completo**

    ---

    De una consulta a arXiv a un catálogo publicado y una memoria consultable
    de los artículos en los que se basa.

    [Recorrido](guide/migrating-a-pipeline.md) ·
    [udg-catalogue](https://github.com/xueromll/udg-catalogue)

- **Empieza**

    ---

    Instala los extras que necesites y ejecuta tu primer pipeline sobre arXiv;
    después apúntalo a [PubMed, Semantic Scholar u OpenAlex](guide/sources.md).

    [Instalación](getting-started/installation.md) ·
    [Inicio rápido](getting-started/quick-start.md)

- **Busca en lo que has recopilado**

    ---

    Búsqueda booleana e híbrida, facetas de metadatos y grafos de artículos
    relacionados sobre un índice SQLite local.

    [Búsqueda y descubrimiento locales](guide/search/index.md)

- **Consulta una API**

    ---

    Todas las clases y funciones públicas, generadas a partir del código
    fuente.

    [Referencia de la API](reference/index.md)

</div>

## Características {#features}

- **Interfaces asíncronas intercambiables** para cada etapa: `AsyncExtractor`,
  `Parser`, `AsyncLLMClient`, `AsyncRelevanceFilter`, `AsyncEntityExtractor`,
  `AsyncExporter`, `AsyncStateManager`, además de `AsyncEmbedder`,
  `TextChunker` y `AsyncEmbeddingStore` para la memoria semántica. Ejecuta el
  pipeline completo o usa solo las partes que necesites, como la búsqueda.
- **Orquestación asíncrona ante todo**: cada componente es una implementación
  `async`. `AsyncETLPipeline` procesa registros con concurrencia limitada, y
  `ETLPipeline` ejecuta el mismo pipeline desde código bloqueante.
- **Señalización explícita de fallos**: un fallo de transporte o un listado mal
  formado aborta la ejecución con `PipelineAborted` (que lleva el recuento
  parcial) en lugar de parecer el final de los datos. Un registro que falla se
  registra y queda para la siguiente ejecución, y los registros que siguen
  fallando mientras no se procesa nada detienen la ejecución en lugar de
  consumir el resto del listado.
- **Estado reanudable y a prueba de fallos**: los backends de archivos planos
  o de SQLite registran los identificadores procesados, el cursor del listado y
  los intentos fallidos, así que un registro que sigue fallando se pone en
  cuarentena; las escrituras de CSV y de metadatos usan renombrados atómicos.
  Los listados de más recientes primero recogen los artículos nuevos sin volver
  a recorrerlo todo.
- **Apagado ordenado**: Ctrl+C o SIGTERM deja terminar los registros en curso,
  vuelca el estado y lanza `PipelineInterrupted`.
- **Reintentos y límites de frecuencia respetuosos**: todos los extractores
  incluidos y los clientes de chat y embeddings compatibles con OpenAI esperan
  el tiempo que pida la cabecera `Retry-After` de una respuesta limitada, hasta
  un máximo configurable, y aceptan limitadores de frecuencia que pueden
  compartirse y fijarse por host.
- **Eventos de progreso, métricas y consumo de tokens**: eventos tipados por
  registro, métricas de ejecución con recuentos, duraciones y fallos, y los
  tokens que usó cada ejecución.
- **Extracción tipada y afirmaciones**: describe una entidad con un modelo de
  Pydantic para obtener entidades tipadas y validadas y los motivos de cada
  rechazo, o extrae afirmaciones que conservan el artículo, la frase de
  evidencia y el modelo detrás de cada valor.
- **Caché de respuestas del LLM**: una caché en memoria o en SQLite responde a
  los prompts repetidos sin otra llamada a la API.
- **Memoria semántica (opcional)**: fragmenta textos completos y guarda sus
  embeddings en un almacén vectorial en memoria o en SQLite, busca artículos
  similares o decide la relevancia por similitud de embeddings en lugar de con
  una llamada al LLM.
- **Búsqueda y descubrimiento locales**: consultas booleanas sobre un índice de
  texto SQLite FTS5 que solo necesita la biblioteca estándar, búsqueda híbrida
  que fusiona BM25 con la similitud de embeddings, facetas de metadatos y grafos
  de artículos relacionados.
- **Inyección de dependencias en todas partes**: los clientes HTTP, los
  analizadores, los modelos, los prompts, los esquemas y las rutas de salida
  son argumentos del constructor.
- **Implementaciones concretas incluidas**: extractores de arXiv, PubMed,
  Semantic Scholar y OpenAlex; clientes de chat y embeddings compatibles con
  OpenAI; generador local de embeddings con sentence-transformers;
  analizadores de PDF / LaTeX / HTML / DOCX / JATS XML; exportadores CSV y JSON
  Lines; sumideros de tablas SQL y de gráficos 3D de Plotly; procesadores de
  dataframes y validadores de registros.
- **Configuración tipada** desde YAML y variables de entorno, con validación de
  Pydantic y claves de API como `SecretStr`.
- **Batería de pruebas sin conexión**: pytest con mocks, pruebas de propiedades
  con Hypothesis y pruebas de conformidad con las ABC.
- **Tipado según PEP 561** (`py.typed`) para la comprobación de tipos en el
  código que la use.

## Obtener ayuda {#getting-help}

- Las preguntas y los errores van al
  [gestor de incidencias](https://github.com/xueromll/sci-etl-core/issues).
- ¿Vas a trasladar un pipeline existente a la biblioteca? Sigue el
  [ejemplo práctico](guide/migrating-a-pipeline.md). ¿Vas a actualizar a una
  nueva versión? Consulta la [guía de migración](project/migration.md).
- Las contribuciones son bienvenidas: consulta [Contribuir](project/contributing.md).
- Informa de las vulnerabilidades de forma privada, como se describe en
  [Seguridad](project/security.md).
