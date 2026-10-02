# Entidades tipadas y validación

`AsyncLLMEntityExtractor` devuelve los objetos que escribió el modelo, como
`dict`, a menos que describas una entidad con un modelo de Pydantic. Con
`schema=`, cada entidad se valida contra el modelo antes de salir del
extractor, y el extractor devuelve instancias del modelo:

```python
import os

from pydantic import BaseModel, Field

from sci_etl_core import AsyncLLMEntityExtractor, AsyncOpenAICompatibleClient
from sci_etl_core.processors import NumericRangeValidator


class Galaxy(BaseModel):
    name: str
    ra_deg: float | None = Field(default=None, description="Right ascension, decimal degrees, ICRS")
    dec_deg: float | None = Field(default=None, description="Declination, decimal degrees, ICRS")
    effective_radius_kpc: float | None = None


llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
    structured_output=True,
)
extractor = AsyncLLMEntityExtractor(
    llm,
    "Extract every ultra-diffuse galaxy the paper reports. Reply with JSON: {\"galaxies\": [...]}.",
    schema=Galaxy,
    result_key="galaxies",
    validator=NumericRangeValidator({"ra_deg": (0.0, 360.0), "dec_deg": (-90.0, 90.0)}),
    label_field="name",
)
```

## Salida estructurada {#structured-output}

La solicitud pide que toda la respuesta, una lista de entidades bajo
`result_key`, se ajuste a un JSON Schema construido a partir del modelo;
`entity_list_schema(Galaxy, "galaxies")` lo devuelve.
`AsyncOpenAICompatibleClient(structured_output=True)` lo envía como formato de
respuesta `json_schema`. Deja `structured_output` desactivado para un endpoint
que no admita ese formato, como el de DeepSeek: la solicitud sale entonces en
modo JSON, el prompt debe seguir describiendo los campos y cada entidad se
sigue validando.

Un cliente propio obtiene salida estructurada sobrescribiendo
`complete_structured(system_prompt, user_content, schema, timeout)`. La
implementación por defecto llama a `complete_json`, así que cualquier cliente
funciona con la extracción tipada.

El esquema forma parte de la clave de la caché del LLM, así que cambiar la
clase del modelo nunca sirve una respuesta guardada para la anterior; consulta
[Caché de respuestas del LLM](llm-caching.md).

## Rechazos y sus motivos {#rejections-and-their-reasons}

Una entidad se rechaza cuando no cumple el esquema o cuando `validator` la
rechaza. El validador ve la entidad como un `dict`, después de la comprobación
del esquema. Cada rechazo se registra con nivel `INFO` en el logger
`sci_etl_core.llm.extraction_async`, junto con sus motivos:

```text
Entity rejected by validation: 'DF44' (ra_deg is 412, outside [0, 360])
```

`RecordValidator.validate(entity)` devuelve un `ValidationResult` cuyas
`violations` indican cada una un `code`, un `field`, una `severity` y un
`message`. `NumericRangeValidator` informa `"out-of-range"` y
`"not-a-number"`, `KeywordExclusionValidator` informa `"null-key"` y
`"forbidden-keyword"`, un fallo del esquema informa `"schema"`, y
`CompositeValidator` reúne las infracciones de todos los validadores que
contiene. Un validador propio que solo implementa `is_valid` sigue
funcionando: sus rechazos aparecen como `"rejected"`. Sobrescribe `validate`
para explicar el motivo:

```python
from sci_etl_core.processors import RecordValidator, ValidationResult, Violation


class NoPaperLocalNames(RecordValidator):
    def is_valid(self, record):
        return self.validate(record).ok

    def validate(self, record):
        name = str(record.get("name", ""))
        if name.isdigit():
            return ValidationResult(
                violations=(
                    Violation(code="paper-local-name", field="name", severity="error", message=f"{name!r} is a table index"),
                )
            )
        return ValidationResult()
```

Una infracción con `severity="warning"` se notifica, pero no rechaza la
entidad.

## Conservar las entidades rechazadas para revisarlas {#keeping-rejected-entities-for-review}

Pasa un almacén de rechazos y cada entidad rechazada se conservará con sus
infracciones, su identificador de registro y el sello del modelo y el prompt
que la produjeron, de modo que un validador que rechaza demasiado se hace
visible:

```python
from sci_etl_core.claims import AsyncSqliteRejectionStore

rejections = AsyncSqliteRejectionStore("review/rejections.db")
extractor = AsyncLLMEntityExtractor(llm, "Extract galaxies as JSON.", schema=Galaxy, rejections=rejections)


async def review() -> None:
    for entry in await rejections.unresolved(limit=20):
        print(entry.record_id, entry.entity, [violation.message for violation in entry.violations])
        await rejections.resolve(entry.entry_id, "rejection upheld")
```

Rechazar la misma entidad otra vez en una ejecución posterior conserva una
sola entrada, con su resolución. Un fallo del almacén de rechazos hace fallar
el registro, que se reintenta en la siguiente ejecución. Una *entidad
rechazada* no tiene relación con un *registro en cuarentena*, que es un
registro que el pipeline omite después de que haya fallado `max_attempts`
veces.

## Extractores que usan el registro {#record-aware-extractors}

El pipeline llama a `extract_record(record, text)`. Su implementación por
defecto llama a `extract(text)`, así que un extractor que solo sobrescribe
`extract` funciona sin cambios. Un extractor que necesita el registro, como
`AsyncLLMClaimExtractor`, fija `requires_record = True`, y su `extract` lanza
`TypeError`. Un extractor que envuelve a otro llama al `extract_record` del
interno y copia su `requires_record`:

```python
from sci_etl_core import AsyncEntityExtractor


class CountingExtractor(AsyncEntityExtractor):
    def __init__(self, inner):
        self.inner = inner
        self.requires_record = inner.requires_record
        self.calls = 0

    async def extract(self, text):
        return await self.inner.extract(text)

    async def extract_record(self, record, text):
        self.calls += 1
        return await self.inner.extract_record(record, text)
```

`AsyncLLMEntityExtractor.prepare(text)` devuelve el texto que se envía al
modelo, después de quitar el marcado y truncar, y `stamp` describe el modelo,
el prompt, el esquema y la versión de la biblioteca que hay detrás de sus
entidades.
