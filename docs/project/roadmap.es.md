# Hoja de ruta

Esta hoja de ruta marca una dirección, no compromisos. Las prioridades siguen
casos de uso reales, y cada elemento debe encajar en el alcance de la
biblioteca: artículos científicos de entrada, datos estructurados y
consultables de salida. Un elemento que no encaja se descarta, por útil que
fuera en otro sitio. Para trabajar en un elemento, comenta en su incidencia o
abre una. Los elementos marcados como **good first issue** son adecuados para
quien empieza.

Cada hito enumera sus criterios de salida. Un hito se publica cuando se cumplen
todos los criterios con la batería de pruebas sin conexión y una cobertura de
líneas del 100 %.

## Versión actual — v0.6.0 {#current-release-v060}

[CHANGELOG.md](changelog.md) enumera todos los cambios por versión, y
[MIGRATION.md](migration.md) explica cómo actualizar desde la 0.4 y qué cambian
la 0.5 y la 0.6.

| Consumidor | Requiere | Ejecuta |
|------------|----------|---------|
| [udg-catalogue](https://github.com/xueromll/udg-catalogue) | `>=0.6.0.dev0,<0.7` en `main`, con todos los extras que importa, y su batería de pruebas pasa contra `master` del núcleo | 0.4 en producción, incluidos la búsqueda, el descubrimiento y los embeddings |
| [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) | `>=0.6.0.dev0,<0.7` en `master`, y su batería de pruebas pasa contra `master` del núcleo; su próxima versión, la 0.4.0, requiere `>=0.6.0,<0.7` | 0.2, en su última versión 0.2.1 |

| Área | Publicado |
|------|-----------|
| Orquestación | `AsyncETLPipeline` con concurrencia limitada por registro, `total_limit` exacto, detección de atascos y `PipelineAborted` con recuentos parciales; `ETLPipeline` como fachada bloqueante sobre un bucle de eventos en segundo plano |
| Contratos | ABC para extractores, filtros de relevancia, extractores de entidades, clientes del LLM, exportadores, gestores de estado, analizadores, generadores de embeddings, fragmentadores, almacenes vectoriales y de texto, procesadores y validadores; extractores de entidades y exportadores genéricos en el tipo de entidad |
| Entrega | Los exportadores reciben cada registro con sus entidades mediante `open`, `write`, `flush` y `aclose`, y un registro se marca como procesado solo cuando sus entidades son duraderas, así que un fallo puede repetir un registro pero nunca perderlo; `AsyncCsvExporter` con una fila por entidad y `AsyncJsonlExporter` con una línea por registro, ambos lineales en el número de registros |
| Fiabilidad | Apagado ordenado mediante `ShutdownSignal`, estado volcado termine como termine una ejecución, escrituras atómicas y cerrojos de archivo del sistema operativo, reintentos que respetan `Retry-After`, limitadores de frecuencia compartidos y por host, límites de tamaño de descarga y de descompresión |
| Reanudación | Cursores de listado guardados que solo avanzan más allá de páginas resueltas, límites de resultados notificados como truncamiento con la siguiente ejecución empezando desde la primera página, una cuarentena para los registros que siguen fallando, estado versionado por esquema que actualiza los archivos escritos por la 0.4, y ejecuciones `newest_first` que recogen los envíos nuevos sin volver a recorrerlo todo |
| Fuentes | Extractores de arXiv, PubMed, Semantic Scholar y OpenAlex; analizadores de PDF, LaTeX, HTML, DOCX y JATS XML |
| LLM | Clientes de chat y embeddings compatibles con OpenAI con consumo de tokens y salida estructurada por JSON Schema, caché de respuestas en memoria o en SQLite con clave en el esquema de la entidad, entidades tipadas validadas contra un modelo de Pydantic |
| Afirmaciones (provisional) | `sci_etl_core.claims`: cada valor extraído con su artículo, su frase de evidencia y el modelo, el prompt y el esquema que lo produjeron; almacenes de afirmaciones y de rechazos en memoria o en SQLite; validadores que nombran el campo y la regla detrás de cada rechazo |
| Memoria y búsqueda | Memoria vectorial, lenguaje de consultas booleano con `NEAR`, almacenes de texto SQLite FTS5 y en memoria, fusión híbrida de clasificaciones, filtros de rango y de metadatos, facetas, extractos, grafos de descubrimiento y relleno desde la memoria vectorial |
| Configuración | Modelos de Pydantic cargados desde YAML, con `.env` leído solo bajo petición, claves `SecretStr`, errores de validación que no revelan secretos y constructores `from_config` |
| Instalación | Una instalación base que solo requiere `pydantic`, con cada analizador, cargador, extractor y procesador detrás del extra que necesita |
| Observabilidad | `logging` estándar bajo el logger `sci_etl_core`, eventos de progreso y `RunMetrics` con recuentos, duraciones, resultado y consumo de tokens |
| Salud del proyecto | Batería de pruebas pytest e Hypothesis sin conexión con un 100 % de cobertura de líneas y cobertura de ramas notificada; ruff con los conjuntos de reglas `ASYNC`, `UP`, `RUF` y `PT`, y mypy con opciones más estrictas en los contratos principales; CI en Linux, Windows y macOS para Python 3.11–3.14, publicación de confianza en PyPI, un sitio de documentación con una referencia de la API generada |
| Salvaguardas | Una instantánea incluida en el repositorio de todas las firmas estables, que también cubre todos los nombres que usa un consumidor conocido; las garantías de `AsyncETLPipeline.run` numeradas en una guía de semántica de ejecución, cada una con una prueba con nombre; una comprobación en la CI de que cada nombre estable se importa desde una instalación base o desde el extra que necesita su componente; las baterías de pruebas de sci-etl-cli y udg-catalogue se ejecutan en cada cambio del núcleo y bloquean cada versión; pruebas de humo nocturnas contra cada fuente incluida; un benchmark de rendimiento que pasa cada exportador por el pipeline |

Pendiente:

- sci-etl-cli 0.4.0 y udg-catalogue sobre la 0.6.0 publicada, requiriendo
  `>=0.6.0,<0.7` en lugar de una versión de desarrollo y funcionando sin
  `DeprecationWarning`.
- Una comprobación real de cuánto tiempo siguen siendo válidos los cursores de
  OpenAlex.

PubMed y Semantic Scholar mantienen la paginación por desplazamiento y notifican
sus límites como truncamiento: E-utilities sirve como máximo 9999 resultados
incluso a través de su servidor de historial, y la búsqueda masiva de Semantic
Scholar devuelve páginas fijas de 1000 artículos, lo que no permite respetar
`page_size`.

## Camino hacia la 1.0 {#path-to-10}

Todos los contratos públicos han tenido ya su última ruptura prevista antes de
la 1.0. El contrato de ejecución (extractor, estado, constructor) se rompió en
la 0.5.0 y el contrato de datos (entidades, exportador, registro, dependencias)
en la 0.6.0; todas las versiones posteriores son aditivas. Cada cambio
incompatible tiene una entrada en [MIGRATION.md](migration.md).

Desde la 0.6.0, un nombre obsoleto sigue funcionando durante al menos dos
versiones menores antes de eliminarse. Una versión solo se etiqueta cuando las
baterías de pruebas de sci-etl-cli y udg-catalogue pasan contra el commit de la
versión; el flujo de publicación ejecuta ambas y, si no, se niega a publicar.

## v0.7.0 — Funciones aditivas y el kit de pruebas {#v070-additive-features-and-the-testing-kit}

Sin cambios incompatibles y sin nuevas obsolescencias.

- **Reprocesamiento selectivo.** Un contrato opcional `forget(record_ids)`, que
  implementan los dos gestores de estado incluidos, permite volver a extraer
  registros sin descartar todo el estado.
- **Filtros de relevancia en cascada.** Un filtro compuesto ejecuta un filtro
  barato, como `AsyncEmbeddingRelevanceFilter`, antes del filtro con LLM.
- **Kit de pruebas.** `sci_etl_core.testing` ofrece baterías de pruebas de
  contrato que pueden ejecutar los extractores, gestores de estado,
  exportadores y almacenes de embeddings de terceros.

## v1.0.0 — Estabilización {#v100-stabilization}

La 1.0.0 garantiza tres niveles: los nombres estables siguen el versionado
semántico, los nombres provisionales pueden cambiar en una versión menor con
una entrada en el registro de cambios, y los nombres privados pueden cambiar en
cualquier momento. Todo nombre que importa un consumidor conocido es estable.
La versión candidata se etiqueta cuando se haya publicado una versión menor
completa sin cambios incompatibles, la instantánea de la superficie pública y
las pruebas de semántica de ejecución bloqueen cada cambio, y los archivos
escritos por la 0.6.0 y la 0.7.0 se abran en ella.

## Más adelante {#later}

Estos elementos esperan a un consumidor que los necesite, o a una medición.

- **Síntesis de conocimiento (sci-etl-kg).** Normalización de unidades,
  consolidación de mediciones repetidas y tamaños del efecto agrupados sobre
  las afirmaciones de la 0.6.0, en un paquete aparte construido sobre la
  1.0.0. Hasta que se cumpla la regla de inicio de abajo, este trabajo sigue en
  udg-catalogue, porque una capa construida a partir de un solo catálogo
  incorporaría las suposiciones de ese catálogo. El núcleo nunca importa
  sci-etl-kg, así que ningún resultado de los de abajo afecta a quienes usan el
  núcleo.
    - **Segundo catálogo.** Una vez publicada la 1.0.0, cuando un segundo
      consumidor que construya un catálogo necesite normalización de unidades o
      consolidación, sci-etl-kg 0.1 empezará solo con esas dos funciones,
      construidas sobre nombres estables.
    - **Sin segundo catálogo.** Si en septiembre de 2027 no existe un segundo
      catálogo, sci-etl-kg pasa a "No previsto" hasta que aparezca uno.
    - **Seis meses sin actividad.** Si sci-etl-kg pasa seis meses sin una
      versión, o su mantenimiento retrasa una versión del núcleo, su última
      versión 0.x se congela, se marca como sin mantenimiento y se archiva.
    - **Detección de contradicciones.** La detección de contradicciones y los
      grafos causales quedan fuera de todo plan de versiones; los notebooks y
      las ramas de investigación son el límite.
- **Memoria vectorial escalable.** Un `AsyncEmbeddingStore` de vecinos más
  cercanos aproximados para corpus que el almacén SQLite de recorrido exacto no
  puede atender de forma interactiva. Empezará cuando un corpus defina el
  tamaño y la latencia objetivo.
- **Ajuste del grupo de candidatos.** Medir cuántos registros distintos abarcan
  los primeros fragmentos en una base de datos de memoria real, como la de
  udg-catalogue, y fijar el valor por defecto de `chunk_pool_factor` a partir
  de la medición.
- **Exportación en columnas.** Un sumidero Parquet para las tablas
  posprocesadas, detrás de un extra opcional.
- **Análisis de PDF en una sola pasada.** `PdfPlumberParser.extract_text` abre
  cada PDF dos veces, una para el texto y otra para las tablas. Leer ambos en
  una sola pasada.
- **Aristas de citas.** Una fuente de aristas para la cocitación y el
  acoplamiento bibliográfico, construida sobre las listas de referencias que
  `AsyncOpenAlexExtractor` guarda en `metadata["references"]`.
- **Coincidencias de subcadenas y CJK.** Un índice de texto opcional de
  trigramas, que aproximadamente duplica el tamaño del índice.
- **Interfaz de descubrimiento.** Una vista interactiva de búsqueda y de grafo
  sobre el modelo de lectura `sci_etl_core.discovery`, construida fuera de este
  repositorio como un subcomando de sci-etl-cli o una aplicación aparte.

## Exploratorio {#exploratory}

- **Clientes nativos de proveedores.** Los servidores locales como vLLM,
  llama.cpp y Ollama ya funcionan mediante el cliente compatible con OpenAI. Un
  cliente nativo solo merece la pena para un proveedor sin endpoint compatible
  con OpenAI, o para uno cuyo soporte de salida estructurada le falte a ese
  endpoint.

## No previsto {#not-planned}

Estos elementos se consideraron y se retiraron; algunos aparecieron en hojas de
ruta anteriores.

- **Contratos de orquestación bloqueantes.** La API asíncrona es la
  admitida. Los componentes hoja bloqueantes, como los analizadores y los
  procesadores de pandas, siguen siendo bloqueantes; los contratos bloqueantes
  de extractor, estado, exportador, LLM, relevancia y entidades, sus
  adaptadores y las correcciones del puente que hay debajo se retiran en favor
  de sus equivalentes asíncronos.

- **Ensamblado por configuración en la biblioteca.** sci-etl-cli ya construye
  un pipeline completo a partir de un único archivo YAML. La biblioteca aporta
  los constructores `from_config`; el ensamblado declarativo se queda en la
  CLI, así que el núcleo no incluye un registro de componentes.
- **Modo de pipeline en streaming.** `on_event` ya informa de cada registro a
  medida que termina. Entregar registros antes de que la página se resuelva
  entraría en conflicto con la regla de que el desplazamiento guardado solo
  avanza más allá de páginas completamente resueltas.
- **Puntos de control de los procesadores.** Las cadenas de procesadores son
  transformaciones en memoria con pandas de una tabla exportada, que ya es el
  punto de control duradero; volver a ejecutar la cadena es más barato que
  persistir cada paso.
- **Ejecución distribuida.** Los gestores de estado dependen de cerrojos de
  archivos locales y de un único escritor de SQLite. Repartir un corpus entre
  ejecuciones independientes, cada una con su propio estado, cubre los corpus
  grandes sin un entorno de ejecución distribuido.
- **Renombrar `sci-etl-core` o `sci_etl_core`.** Los nombres de la
  distribución y de importación se mantienen. Un cambio de nombre requeriría
  una versión puente y una migración en cada consumidor, y no cambiaría nada de
  lo que hace la biblioteca.
- **Un metapaquete `sci-etl`.** sci-etl-cli ya depende del núcleo con los
  extras que necesita, así que un metapaquete solo añadiría una publicación más
  a cada versión.
- **Volver a publicar `sci-etl-cli` como `sci-etl`.** La CLI ya se publica en
  PyPI como sci-etl-cli e instala el comando `sci-etl`. Un nuevo nombre de
  distribución sería otro cambio de nombre, con su propia versión puente.

---

¿Tienes un caso de uso que la hoja de ruta no cubre? Abre una
[solicitud de función](https://github.com/xueromll/sci-etl-core/blob/master/.github/ISSUE_TEMPLATE/feature_request.md).
