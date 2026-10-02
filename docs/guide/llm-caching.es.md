# Caché de respuestas del LLM

Volver a ejecutar un pipeline después de un fallo, de un ajuste de prompt en
otro sitio o de un cambio en el código de exportación hace al LLM las mismas
preguntas otra vez. `CachingLLMClient` responde a las solicitudes repetidas
desde una caché, así que no cuestan tokens y vuelven al instante:

```python
from sci_etl_core import (
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    AsyncSqliteLLMResponseCache,
    CachingLLMClient,
)

cache = AsyncSqliteLLMResponseCache("cache/llm.db")
llm = CachingLLMClient(AsyncOpenAICompatibleClient.from_config(config.llm), cache)

relevance_filter = AsyncLLMRelevanceFilter(llm, relevance_prompt)
entity_extractor = AsyncLLMEntityExtractor(llm, extraction_prompt)
```

Incluye la caché SQLite en los `closeables` del pipeline para que su conexión
se cierre al final de la ejecución.

## Cómo se comparan las solicitudes {#how-requests-are-matched}

La clave de una solicitud se forma con el nombre del modelo, el `base_url` del
endpoint, la temperatura, el formato de respuesta, el JSON Schema de una
solicitud tipada, el `variant` del cliente y ambos prompts, con hash SHA-256;
el tiempo de espera no forma parte de la clave. Un prompt de sistema
modificado, un texto de artículo modificado, otro modelo, otro proveedor, otra
temperatura, otro formato de respuesta o un esquema de entidad modificado es un
fallo de caché. El esquema se serializa con las claves ordenadas, así que un
esquema igual escrito en otro orden sigue acertando. Una solicitud sin esquema
y con un `variant` vacío tiene la misma clave que en 0.5.1.

`CachingLLMClient(..., variant="sample-2")` mantiene sus respuestas separadas
de las de un cliente con otra variante sobre la misma caché, por ejemplo para
hacer una pregunta dos veces a propósito.

`CachingLLMClient` lee `base_url`, `temperature` y `response_format` del
cliente que envuelve. `AsyncOpenAICompatibleClient` expone los tres. Todo
cliente tiene un `response_format`, `{"type": "json_object"}` salvo que una
subclase lo sobrescriba; un cliente personalizado sin `base_url` o
`temperature` obtiene una clave sin ellos.

## Qué se almacena en caché {#what-is-cached}

Una solicitud que falló nunca se guarda en caché, así que se vuelve a enviar
la próxima vez. Tampoco se conserva una respuesta que la biblioteca rechaza:

- `AsyncLLMEntityExtractor` rechaza una respuesta que no contiene una lista de
  entidades, o cuya lista de entidades no es una lista de objetos.
- `AsyncLLMRelevanceFilter` rechaza una respuesta sin un veredicto claro.

Ambos llaman a `invalidate` en el cliente, y `CachingLLMClient` borra la
respuesta guardada, de modo que el reintento en la siguiente ejecución llega al
modelo en lugar de repetir la misma respuesta.

## Backends {#backends}

- **`InMemoryLLMResponseCache(max_entries=None)`** vive lo mismo que el
  proceso. Con `max_entries`, la respuesta usada hace más tiempo se expulsa
  cuando se llena.
- **`AsyncSqliteLLMResponseCache(path)`** conserva las respuestas en un
  archivo SQLite entre ejecuciones. `clear()` lo vacía y `count()` informa de
  su tamaño.

Un backend personalizado, como Redis, hereda de `AsyncLLMResponseCache` e
implementa `get`, `set`, `delete` y `clear`. Un backend sin `delete` sigue
funcionando, pero cada respuesta rechazada permanece en caché y se registra
como un fallo de caché.

## Cuando la caché falla {#when-the-cache-fails}

La caché nunca hace fallar una petición al modelo. Si leerla o escribirla lanza
una excepción, el error se registra como `LLM cache get failed: ...`,
`LLM cache set failed: ...` o `LLM cache delete failed: ...`, con nivel
`WARNING`, en el logger `sci_etl_core.llm.cache_async`, y la solicitud va al
LLM como si no hubiera nada en caché. `stats` cuenta `hits`, `misses` y
`faults`, y `usage` es el del cliente envuelto, así que los aciertos de caché no
cuestan tokens:

```python
print(llm.stats, llm.usage)
```
