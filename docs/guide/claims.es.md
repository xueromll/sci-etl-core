# Afirmaciones y procedencia

Una afirmación es un valor o enunciado extraído de un artículo y guardado junto
con el artículo del que procede, la frase de la que se leyó y el modelo, el
prompt y el esquema que la produjeron. Las afirmaciones permiten que una tabla
responda "¿qué artículo lo dice?" para cada valor, mantener juntos los datos
contradictorios y encontrar todos los valores que hay que rehacer después de
corregir un prompt.

!!! note "Provisional"
    `sci_etl_core.claims` es nuevo en 0.6.0 y provisional: un nombre puede
    cambiar en una versión menor, con una entrada en el CHANGELOG, hasta que un
    consumidor conocido dependa de él.

## Extraer afirmaciones {#extracting-claims}

`AsyncLLMClaimExtractor` pide al modelo objetos `ClaimDraft`, los valida,
localiza la cita de cada borrador en el texto enviado al modelo y devuelve
objetos `Claim`. `AsyncClaimStoreExporter` los guarda registro a registro:

```python
import os

from sci_etl_core import AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.claims import (
    AsyncClaimStoreExporter,
    AsyncLLMClaimExtractor,
    AsyncSqliteClaimStore,
    AsyncSqliteRejectionStore,
)

CLAIM_PROMPT = (
    "List every measurement of an ultra-diffuse galaxy in the paper. Reply with JSON: "
    '{"claims": [{"kind": "measurement", "subject": "...", "predicate": "effective_radius", '
    '"quantity": {"verbatim": "2.9 kpc", "value": 2.9, "unit_text": "kpc"}, '
    '"context": {"band": "g"}, "quote": "the sentence, copied exactly"}]}.'
)

llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"], base_url="https://api.openai.com/v1", model="gpt-4o-mini"
)
claims = AsyncSqliteClaimStore("data/claims.db")
rejections = AsyncSqliteRejectionStore("data/rejections.db")

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=AsyncLLMClaimExtractor(llm, CLAIM_PROMPT, rejections=rejections),
    exporter=AsyncClaimStoreExporter(claims),
    state_manager=state_manager,
    closeables=[llm, claims, rejections],
)
```

Hereda de `ClaimDraft` para acotar `predicate` o las claves de `context` a tu
campo, y pasa la subclase como `schema=`. El modelo nunca proporciona
identificadores, desplazamientos ni datos de procedencia; los calcula el
código.

## Qué contiene una afirmación {#what-a-claim-holds}

| Campo | Significado |
|-------|-------------|
| `claim_id` | un resumen criptográfico del registro, el tipo, el sujeto, el predicado, el objeto, la polaridad, el contexto, el texto literal de la cantidad, el fragmento y el hash del esquema |
| `kind` | `"measurement"`, que necesita una `quantity`, o `"assertion"`, que necesita un `object` |
| `subject`, `predicate`, `object` | de qué trata la afirmación, tal como lo nombra el artículo |
| `quantity` | el número tal como lo escribe el artículo: `verbatim`, `value`, `unit_text`, `qualifier`, `uncertainty` |
| `statistics` | tamaños del efecto, límites de confianza, *p*, estadísticos de prueba, tamaños de grupo, todos opcionales |
| `context` | condiciones como la banda o la muestra, como pares clave–valor ordenados |
| `span` | el `record_id`, los desplazamientos inicial y final de la frase o frases en las que se encontró la cita, y la propia cita |
| `stamp` | el modelo, el hash del prompt, el hash del esquema y la versión de la biblioteca |

El modelo, el prompt y la versión de la biblioteca quedan fuera de `claim_id`
a propósito: volver a extraer un artículo con otro modelo da los mismos
identificadores allí donde coinciden los campos, con un sello nuevo. Los
sujetos se comparan de forma exacta, así que `"DF44"` y `"DF 44"` son
afirmaciones distintas; resolver los nombres es un paso posterior que nunca
reescribe las afirmaciones. `Claim.to_row()` da un único mapeo plano, la forma
que escriben los almacenes y los exportadores CSV y JSON Lines.

## Anclaje en el texto {#grounding}

`locate_quote(text, quote)` encuentra la cita en el texto enviado al modelo,
de forma exacta después de colapsar los espacios o, si no, de forma aproximada
con `difflib` con un `min_ratio` de 0,9 o superior, y ajusta la coincidencia a
frases completas. El separador de frases conoce la prosa científica: `et al.`,
`Fig. 3`, `Eq. (2)`, `i.e.`, `R.A.` y los decimales no terminan una frase. Un
borrador cuya cita no se encuentra queda sin anclar: se registra, se guarda en
el almacén de rechazos con el código `"ungrounded"` y no se devuelve.

## Almacenes {#stores}

`InMemoryClaimStore` y `AsyncSqliteClaimStore` comparten un mismo contrato:

- `replace_record(record_id, claims)` reemplaza las afirmaciones de un registro
  en una sola transacción y devuelve la nueva revisión. Una lista vacía vacía el
  registro, que es lo que ocurre cuando una nueva extracción no encuentra nada,
  porque el pipeline escribe cada registro procesado.
- `claims_for_records(record_ids)` vuelve a leer las afirmaciones, en el orden
  guardado.
- `changes_since(revision)` recorre por páginas lo que cambió, por revisión,
  que solo crece, de modo que un trabajo posterior puede retomar donde lo dejó.

El almacén SQLite indexa las afirmaciones por registro, por
`(subject, predicate, object)`, por par de contexto y por tipo y valor
canónicos, y registra la versión de su esquema, así que un sci-etl-core
posterior abre los archivos escritos por 0.6.0.

Un fallo del almacén en `AsyncClaimStoreExporter.write` hace fallar el
registro, que se reintenta en la siguiente ejecución y cuenta un intento, como
cualquier registro fallido. No es un fallo de memoria.
