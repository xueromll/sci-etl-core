# Cuándo no usarla

`sci-etl-core` hace una sola cosa: artículos científicos de entrada, datos
estructurados y consultables de salida. Esta página enumera los casos en los
que no es la herramienta adecuada, o en los que tendrías que construir por tu
cuenta más de lo que esperas, para que puedas decidirlo antes de instalarla.

## Necesitas unos pocos valores de un puñado de artículos {#you-need-a-few-values-from-a-handful-of-papers}

Los archivos de estado, los cursores de listado, las ejecuciones reanudables y
las cachés compensan cuando un corpus es demasiado grande para leerlo, cuando
vuelves a extraer a medida que aparecen artículos nuevos o cuando necesitas
rastrear cada valor hasta su origen. Para unos pocos artículos que ya tienes,
leerlos o pegarlos en un asistente de chat es más rápido que escribir prompts,
un modelo de entidad y un pipeline.

## Tus artículos no están en una fuente incluida {#your-papers-arent-on-a-bundled-source}

Los extractores incluidos cubren arXiv, PubMed, Semantic Scholar y OpenAlex.
bioRxiv, ChemRxiv, Crossref, los sitios web de las editoriales y una carpeta de
PDF en tu disco necesitan un `AsyncExtractor` propio. El contrato son tres
métodos, como muestra [Escribir un extractor](../guide/sources.md#writing-an-extractor),
pero si no quieres escribir uno, el pipeline no tiene sobre qué ejecutarse. Los
analizadores, la búsqueda y los componentes del LLM siguen funcionando por su
cuenta.

## Los valores que necesitas están tras un muro de pago {#the-values-you-need-are-behind-a-paywall}

El texto completo procede solo de fuentes abiertas: LaTeX y PDF de arXiv, JATS
XML de PubMed Central y los PDF de acceso abierto que enlazan Semantic Scholar
y OpenAlex. La biblioteca nunca inicia sesión en una editorial ni usa acceso
institucional. Cuando un artículo no tiene texto completo abierto, su registro
recurre al resumen, así que en un campo donde la mayoría de los artículos son
de pago, la mayoría de los registros solo dan al LLM un resumen que leer.

## Los valores están en figuras o páginas escaneadas {#the-values-live-in-figures-or-scanned-pages}

`PdfPlumberParser` lee la capa de texto de un PDF, incluidas sus tablas. No
hace OCR ni lee imágenes, así que un valor que solo aparece en un gráfico, una
figura o una página escaneada es invisible para la extracción. Cuando un PDF no
produce ningún texto, el registro recurre al resumen.

## Cada valor debe ser correcto sin revisión {#every-value-must-be-correct-without-review}

Un LLM lee cada artículo, así que un valor puede ser incorrecto, estar mal
atribuido o faltar. Las entidades tipadas, los validadores de registros y las
[afirmaciones](../guide/claims.md), que conservan la frase de la que se leyó
cada valor, te ayudan a encontrar los errores y a comprobarlos, pero no los
eliminan. Además, el mismo prompt puede dar respuestas distintas con otro
modelo u otra versión del modelo, y la
[caché de respuestas](../guide/llm-caching.md) repite respuestas anteriores en
lugar de hacer determinista al modelo. Si cada valor tiene que ser correcto,
como en una presentación regulatoria o una decisión clínica, prevé la
comprobación manual de cada uno o extrae sin un LLM.

## Necesitas la exhaustividad de una revisión sistemática {#you-need-systematic-review-completeness}

Una ejecución puede pasar por alto artículos relevantes de tres maneras:

- **Límites de las fuentes.** PubMed sirve los primeros 9999 resultados de una
  consulta y Semantic Scholar los primeros 1000. Las consultas más acotadas,
  como por intervalos de fechas, llegan al resto, como explica
  [Semántica de ejecución](../guide/run-semantics.md#capped-listings).
- **Cribado automático.** El filtro de relevancia decide a partir del título y
  el resumen, con un LLM o por similitud de embeddings, así que un artículo
  relevante puede marcarse como irrelevante y no descargarse nunca.
- **Falta de texto completo.** Un artículo leído solo por su resumen puede no
  producir valores aunque su cuerpo los tenga.

Para una revisión que deba dar cuenta de cada artículo incluido y excluido, usa
software de cribado específico con revisores humanos y, si acaso, usa esta
biblioteca con los artículos que incluya ese cribado.

## No puedes enviar el texto de los artículos a un LLM {#you-cant-send-paper-text-to-an-llm}

Cada registro relevante cuesta al menos una llamada al LLM sobre su texto
completo, así que el coste crece con el corpus. Sirve cualquier endpoint que
hable la API de chat de OpenAI, incluidos servidores locales como vLLM,
llama.cpp y Ollama, de modo que el texto puede quedarse en tu equipo. Un
proveedor sin ese tipo de endpoint necesita un `AsyncLLMClient` propio. Sin
ningún LLM, la extracción de entidades no funciona, pero los componentes de
búsqueda y de memoria semántica sí: el índice de texto SQLite solo necesita la
biblioteca estándar, y `AsyncSentenceTransformerEmbedder` genera embeddings en
local.

## Necesitas un servicio de búsqueda o una gran base de datos vectorial {#you-need-a-search-service-or-a-large-vector-database}

La búsqueda se ejecuta en tu equipo sobre archivos SQLite:

- `AsyncSqliteEmbeddingStore` puntúa cada vector almacenado en cada consulta y
  mantiene los vectores en memoria, así que el tiempo de consulta y el uso de
  memoria crecen con el corpus. Todavía no hay un índice de vecinos más
  cercanos aproximados; la [hoja de ruta](../project/roadmap.md#later) lo
  recoge a la espera de un corpus que lo necesite.
- Los gestores de estado dependen de cerrojos de archivos locales y de un único
  escritor de SQLite, y la ejecución distribuida no está prevista. Los corpus
  grandes se cubren repartiéndolos entre ejecuciones independientes, cada una
  con su propio estado.
- No hay servidor, autenticación ni acceso multiusuario.

Para un servicio alojado y multiusuario, o para una búsqueda semántica
interactiva sobre un corpus muy grande, pon los datos en un motor de búsqueda o
una base de datos vectorial específicos, ya sea exportándolos o mediante un
`AsyncEmbeddingStore` propio.

## Buscas texto en chino, japonés o coreano, o necesitas coincidencias dentro de las palabras {#you-search-chinese-japanese-or-korean-text-or-need-substring-matches}

El índice de texto separa las palabras por espacios y signos de puntuación, como
hace el tokenizador `unicode61` de SQLite. Una secuencia de caracteres chinos,
japoneses o coreanos sin espacios se indexa como un solo token, así que buscar
una palabra dentro de ella no encuentra nada, y una consulta de prefijo solo
coincide desde el principio de la secuencia. Tampoco se admiten coincidencias
dentro de las palabras, como encontrar `galaxy` en `protogalaxy`. La búsqueda
semántica sobre embeddings no depende del tokenizador.

## Quieres escribir componentes como código bloqueante {#you-want-to-write-components-as-blocking-code}

`ETLPipeline` ejecuta un pipeline desde código bloqueante, como muestra
[Uso bloqueante](blocking-usage.md), pero los contratos del extractor, el
filtro de relevancia, el extractor de entidades, el cliente del LLM, el
exportador y el gestor de estado son asíncronos. Un componente que escribas tú
tiene que ser una implementación `async`; no está previsto ofrecer versiones
bloqueantes de estos contratos. Los analizadores y los procesadores de pandas
siguen siendo bloqueantes.

## Necesitas una garantía de estabilidad 1.0 {#you-need-a-10-stability-guarantee}

La biblioteca está en la 0.6. Todos los cambios incompatibles previstos antes
de la 1.0 ya se han publicado, y un nombre obsoleto sigue funcionando durante al
menos dos versiones menores, pero los nombres provisionales, como los de
`sci_etl_core.claims`, aún pueden cambiar en una versión menor. Fija un
intervalo de versiones menores, como `>=0.6,<0.7`, y lee la
[guía de migración](../project/migration.md) antes de actualizar.

## Quieres una herramienta gráfica {#you-want-a-graphical-tool}

La biblioteca es una API de Python. [sci-etl-cli](../cli/index.md) ejecuta
pipelines desde un archivo YAML sin código de conexión, pero sigue siendo una
herramienta de línea de comandos. Ninguna de las dos incluye una interfaz
gráfica; la construyes tú, como hace udg-catalogue con su panel de control, y
[Crear una interfaz de usuario](../guide/search/user-interfaces.md) describe lo
que los componentes de búsqueda le dan para representar.

## Tus documentos no son artículos científicos {#your-documents-arent-scientific-papers}

Los analizadores leen PDF, HTML, DOCX, LaTeX y JATS XML de cualquier origen,
pero los extractores, los metadatos de los registros y los campos de búsqueda
(título, resumen y cuerpo) dan por hecho que se trata de artículos. Las
patentes, los documentos jurídicos, las noticias y las páginas web encajan mal,
y las funciones para ellos quedan fuera del alcance de la biblioteca. Un
framework general de procesamiento de documentos se adapta mejor a ellos.

## Si nada de esto se aplica {#if-none-of-these-apply}

Empieza por la [Instalación](installation.md) y el
[Inicio rápido](quick-start.md).
