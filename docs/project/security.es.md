# Política de seguridad

Nos tomamos en serio la seguridad de `sci-etl-core` y de sus usuarios. Gracias
por ayudar a mantener seguros el proyecto y su comunidad.

## Versiones compatibles {#supported-versions}

| Versión | Compatible |
|---------|------------|
| 0.6.x   | ✅         |
| < 0.6   | ❌         |

Las correcciones de seguridad se publican en la última versión menor. Actualiza
antes de informar de problemas en versiones anteriores.

## Informar de una vulnerabilidad {#reporting-a-vulnerability}

**No abras una incidencia pública para las vulnerabilidades de seguridad.**

Informa de forma privada por correo electrónico a
**lanhua1122333@gmail.com** con:

- Una descripción de la vulnerabilidad y de su posible impacto.
- Los pasos para reproducirla (una prueba de concepto, si es posible).
- Las versiones afectadas y los detalles del entorno.
- Cualquier solución que propongas, si tienes una.

### Qué esperar {#what-to-expect}

- **Acuse de recibo** en un plazo de 48 horas.
- Una **evaluación** inicial en un plazo de 5 días hábiles.
- Divulgación coordinada: acordaremos contigo un calendario, publicaremos una
  corrección y te daremos crédito en las notas de la versión, salvo que
  prefieras permanecer en el anonimato.

Danos un tiempo razonable para corregirla antes de cualquier divulgación
pública.

## Gestión de secretos {#secret-management}

`sci-etl-core` está diseñada para mantener las credenciales fuera del código,
de los registros y del control de versiones:

- **`SecretStr` para las claves de API.**
  - `LLMConfig.api_key` es un `SecretStr` de Pydantic, así que las claves no
    aparecen en las representaciones, en las líneas de registro ni en las
    trazas.
  - `AsyncOpenAICompatibleClient` y `AsyncOpenAIEmbedder` aceptan
    directamente un `SecretStr` y solo lo desenvuelven cuando crean el cliente
    subyacente.
- **Secretos procedentes del entorno.**
  - `load_config` lee la clave de una variable de entorno (`LLM_API_KEY` por
    defecto; configurable con `api_key_env_var`).
  - Un archivo `.env` solo se lee cuando pasas `env_path` o `load_env=True`, y
    las variables ya definidas en el entorno tienen prioridad sobre él.
- **Mantén las claves fuera de YAML.** Una variable de entorno definida
  siempre prevalece sobre `llm.api_key` del archivo YAML, que solo sirve de
  respaldo. Una clave incluida en un archivo de configuración del repositorio
  sigue siendo una filtración.
- **Los errores de configuración no muestran los valores.** `load_config`,
  `load_config_async` y `validate_config` indican cada clave errónea y el
  motivo, pero nunca su valor, y no encadenan el error de pydantic, que puede
  contener los ajustes sin procesar. El YAML se analiza con `yaml.safe_load`.
- **Nunca incluyas `.env` en el repositorio.** Añade `.env` a `.gitignore` y
  distribuye un `.env.example` con valores de ejemplo, como hace este
  repositorio.
- **Las URL de bases de datos también son secretos.** `SqlTableSink` recibe su
  URL de SQLAlchemy como una cadena `url` normal. Constrúyela a partir del
  entorno en tiempo de ejecución y no la registres.

## Tratamiento de los datos {#data-handling}

- **El texto almacenado no está cifrado.**
  - `AsyncSqliteEmbeddingStore` y `AsyncSqliteFts5Store` persisten pasajes del
    texto completo con sus títulos y URL de origen.
  - `AsyncSqliteLLMResponseCache` persiste las respuestas del modelo como JSON.
  - `AsyncSqliteClaimStore` y `AsyncSqliteRejectionStore` persisten los valores
    extraídos con las frases de evidencia citadas de cada artículo.
  - Los archivos y bases de datos de estado, que registran el último error de
    cada registro fallido, y las salidas CSV y JSON Lines son archivos
    normales.
  - Si tu corpus tiene licencia o es sensible, usa los permisos del sistema de
    archivos y el cifrado en reposo.
- **Inyección de fórmulas en CSV.** Cada celda procede directamente de la
  salida del LLM. `AsyncCsvExporter` antepone por defecto un apóstrofo a
  cualquier celda que empiece por `=`, `+`, `-`, `@`, un tabulador o un retorno
  de carro, para que las hojas de cálculo no la evalúen. Los números simples
  como `-5.361` no se modifican. Mantén `escape_formulas` activado para los
  archivos que la gente abre en programas de hojas de cálculo. Las demás
  salidas —JSON Lines de `AsyncJsonlExporter`, tablas SQL de `SqlTableSink`,
  texto emergente de Plotly de `Plotly3DSink` y tus propios exportadores y
  sumideros— no se escapan.
- **Ningún secreto en las salidas.** Los exportadores solo escriben los datos
  que reciben; elimina los campos con credenciales antes de exportar.

## Entradas no fiables {#untrusted-input}

- **Documentos de terceros.**
  - El análisis de PDF y LaTeX se ejecuta sobre contenido descargado.
  - Los archivos tar de LaTeX se leen en memoria (sus miembros nunca se
    extraen al disco). Los tamaños de descarga y de descompresión no tienen
    límite por defecto, así que un archivo hostil puede agotar la memoria.
  - Limítalos: pasa `max_download_bytes` a los extractores, que limita cada
    cuerpo de respuesta después de decodificarlo, y `max_tex_bytes` a
    `LatexTarballParser`, que limita el TeX descomprimido de un e-print. Una
    descarga de texto completo o un e-print demasiado grandes se registran y se
    omiten.
  - El análisis de PDF no está limitado más allá del tamaño de descarga.
    Procesa los corpus grandes o no fiables en un entorno aislado y con
    recursos limitados.
- **Inyección de prompts.**
  - El texto de los artículos se envía al LLM, y su contenido puede dirigir la
    salida del modelo.
  - Trata las entidades extraídas como no fiables: valídalas (por ejemplo, con
    `NumericRangeValidator` y `KeywordExclusionValidator`) antes de usarlas.
- **Filtros de relevancia que dejan pasar ante un fallo.**
  - `AsyncLLMRelevanceFilter` y `AsyncEmbeddingRelevanceFilter` tienen por
    defecto `default_on_error=True` y `default_on_empty_abstract=True`, así que
    todos los registros pasan durante una caída.
  - Fija `default_on_error=False` si el filtro actúa como control. Entonces el
    filtro se cierra ante un fallo: una llamada fallida o un veredicto poco
    claro lanza una excepción, de modo que el registro ni se extrae ni se marca
    como procesado. El pipeline cuenta un intento fallido y reintenta el
    registro en la siguiente ejecución.
  - `default_on_empty_abstract=False` marca de forma permanente como procesado
    e irrelevante todo registro sin resumen. Fíjalo solo cuando esos registros
    no deban extraerse nunca.
- **Descarga de modelos.**
  - `AsyncSentenceTransformerEmbedder(model_name)` descarga los pesos del
    modelo en el primer uso.
  - Usa un modelo fiable y con versión fijada, o inyecta un `model=` ya cargado
    construido a partir de pesos que hayas verificado.

## Recomendaciones de refuerzo {#hardening-recommendations}

- Rota las claves de API con regularidad y limítalas al mínimo privilegio.
- Fija las versiones de las dependencias y sigue los avisos de seguridad,
  especialmente de:
  - la validación, que necesita cualquier instalación: `pydantic`
  - los clientes de red y del LLM: `httpx`, `aiolimiter`, `openai`, `tiktoken`
  - el análisis de documentos, marcado y configuración: `pdfplumber`,
    `beautifulsoup4`, `lxml`, `pyyaml`, `python-dotenv`
  - los datos y el cálculo numérico: `pandas`, `numpy`, `scikit-learn`
  - el almacenamiento y los gráficos: `SQLAlchemy`, `plotly`
  - `sentence-transformers`, si está instalado
- Valida y sanea cualquier cadena de consulta, ruta de archivo y destino
  proporcionados por usuarios antes de pasarlos a extractores o exportadores.

## Alcance {#scope}

Esta política abarca el código de `sci-etl-core`. Las vulnerabilidades de las
dependencias de terceros deben comunicarse a sus responsables, aunque
agradecemos un aviso para poder fijar versiones o aplicar parches por nuestra
parte.
