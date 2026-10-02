# Reintentos

`AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`,
`AsyncOpenAlexExtractor`, `AsyncOpenAICompatibleClient` y `AsyncOpenAIEmbedder`
reintentan ante limitación de frecuencia (`429`), errores del servidor y fallos
de transporte, con un máximo de `max_retries` intentos por solicitud (3 por
defecto). Los cuatro extractores comparten una misma ruta de reintentos y
reintentan también un `408` de tiempo de espera agotado. `AsyncArxivExtractor`
reintenta además `406`, que la pasarela de arXiv devuelve de forma intermitente
ante solicitudes válidas:

- **Espera exponencial.** Entre intentos esperan `backoff_factor ** attempt`
  segundos: 1 s y luego 2 s con el factor por defecto de 2.
- **`Retry-After`.** Cuando una respuesta indica cuánto esperar, en
  `Retry-After` o en la cabecera `retry-after-ms` que envían las API
  compatibles con OpenAI, esperan ese tiempo en su lugar siempre que sea mayor
  que la espera exponencial, hasta `max_retry_after` segundos (60 por defecto).
- **Una sola capa de reintentos.** Los reintentos propios del SDK de OpenAI
  están desactivados, así que `max_retries` es el número total de intentos.
- **Visibilidad.** Los extractores registran cada reintento y su espera a
  través de `logger`.

El cliente de `build_async_client` también reintenta las conexiones fallidas en
el nivel de transporte (`total_retries`, 5 por defecto) antes de que el
extractor cuente un intento fallido.
