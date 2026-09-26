# Typed entities and validation

`AsyncLLMEntityExtractor` returns the objects the model wrote, as `dict`s,
unless you describe an entity with a Pydantic model. With `schema=`, every
entity is validated against the model before it leaves the extractor, and the
extractor returns model instances:

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

## Structured output

The request asks for the whole answer, a list of entities under `result_key`,
to match a JSON Schema built from the model; `entity_list_schema(Galaxy,
"galaxies")` returns it. `AsyncOpenAICompatibleClient(structured_output=True)`
sends it as a `json_schema` response format. Leave `structured_output` off for
an endpoint that doesn't support that format, such as DeepSeek's: the request
then goes out in JSON mode, the prompt must still describe the fields, and
every entity is still validated.

A client of your own gets structured output by overriding
`complete_structured(system_prompt, user_content, schema, timeout)`. The
default calls `complete_json`, so every client works with typed extraction.

The schema is part of the LLM cache key, so changing the model class never
serves an answer cached for the old one; see
[LLM response caching](llm-caching.md).

## Rejections and their reasons

An entity is rejected when it fails the schema, or when `validator` rejects
it. The validator sees the entity as a `dict`, after the schema check. Each
rejection is logged at `INFO` on the `sci_etl_core.llm.extraction_async`
logger with its reasons:

```text
Entity rejected by validation: 'DF44' (ra_deg is 412, outside [0, 360])
```

`RecordValidator.validate(entity)` returns a `ValidationResult` whose
`violations` each name a `code`, a `field`, a `severity`, and a `message`.
`NumericRangeValidator` reports `"out-of-range"` and `"not-a-number"`,
`KeywordExclusionValidator` reports `"null-key"` and `"forbidden-keyword"`, a
schema failure reports `"schema"`, and `CompositeValidator` collects the
violations of every validator it holds. A validator of your own that
implements only `is_valid` keeps working: its rejections read `"rejected"`.
Override `validate` to say why:

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

A violation with `severity="warning"` is reported but does not reject the
entity.

## Keeping rejected entities for review

Pass a rejection store, and every rejected entity is kept with its
violations, its record id, and the stamp of the model and prompt that
produced it, so a validator that rejects too much is visible:

```python
from sci_etl_core.claims import AsyncSqliteRejectionStore

rejections = AsyncSqliteRejectionStore("review/rejections.db")
extractor = AsyncLLMEntityExtractor(llm, "Extract galaxies as JSON.", schema=Galaxy, rejections=rejections)


async def review() -> None:
    for entry in await rejections.unresolved(limit=20):
        print(entry.record_id, entry.entity, [violation.message for violation in entry.violations])
        await rejections.resolve(entry.entry_id, "rejection upheld")
```

Rejecting the same entity again in a later run keeps one entry, with its
resolution. A rejection store fault fails the record, which is retried on the
next run. A *rejected entity* is unrelated to a *quarantined record*, which is
a record the pipeline skips after it failed `max_attempts` times.

## Record-aware extractors

The pipeline calls `extract_record(record, text)`. Its default calls
`extract(text)`, so an extractor that overrides only `extract` works
unchanged. An extractor that needs the record, such as
`AsyncLLMClaimExtractor`, sets `requires_record = True`, and its `extract`
raises `TypeError`. An extractor that wraps another calls the inner one's
`extract_record` and copies its `requires_record`:

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

`AsyncLLMEntityExtractor.prepare(text)` returns the text the model is sent,
after markup stripping and truncation, and `stamp` describes the model,
prompt, schema, and library release behind its entities.
