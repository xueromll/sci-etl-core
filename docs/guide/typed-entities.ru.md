# Типизированные сущности и валидация

`AsyncLLMEntityExtractor` возвращает объекты, которые написала модель, в виде
`dict`, если только вы не опишете сущность моделью Pydantic. С `schema=` каждая
сущность проверяется по модели, прежде чем покинуть экстрактор, и экстрактор
возвращает экземпляры модели:

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

## Структурированный вывод {#structured-output}

Запрос требует, чтобы весь ответ — список сущностей под `result_key` —
соответствовал JSON Schema, построенной по модели; её возвращает
`entity_list_schema(Galaxy, "galaxies")`.
`AsyncOpenAICompatibleClient(structured_output=True)` отправляет её как формат
ответа `json_schema`. Оставьте `structured_output` выключенным для конечной
точки, которая не поддерживает этот формат, например DeepSeek: тогда запрос
уходит в режиме JSON, промпт по-прежнему должен описывать поля, а каждая
сущность всё равно проверяется.

Собственный клиент получает структурированный вывод, переопределив
`complete_structured(system_prompt, user_content, schema, timeout)`.
Реализация по умолчанию вызывает `complete_json`, поэтому любой клиент
работает с типизированным извлечением.

Схема входит в ключ кэша LLM, поэтому после изменения класса модели никогда не
выдаётся ответ, закэшированный для старой; см.
[Кэширование ответов LLM](llm-caching.md).

## Отклонения и их причины {#rejections-and-their-reasons}

Сущность отклоняется, когда она не проходит схему или когда её отвергает
`validator`. Валидатор видит сущность как `dict`, после проверки схемы.
Каждое отклонение записывается в журнал с уровнем `INFO` в логгер
`sci_etl_core.llm.extraction_async` вместе с причинами:

```text
Entity rejected by validation: 'DF44' (ra_deg is 412, outside [0, 360])
```

`RecordValidator.validate(entity)` возвращает `ValidationResult`, каждое из
`violations` которого называет `code`, `field`, `severity` и `message`.
`NumericRangeValidator` сообщает `"out-of-range"` и `"not-a-number"`,
`KeywordExclusionValidator` — `"null-key"` и `"forbidden-keyword"`, провал
схемы — `"schema"`, а `CompositeValidator` собирает нарушения всех входящих в
него валидаторов. Собственный валидатор, реализующий только `is_valid`,
продолжает работать: его отклонения выглядят как `"rejected"`. Переопределите
`validate`, чтобы объяснить причину:

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

Нарушение с `severity="warning"` сообщается, но не отклоняет сущность.

## Сохранение отклонённых сущностей для проверки {#keeping-rejected-entities-for-review}

Передайте хранилище отклонений, и каждая отклонённая сущность будет сохранена
вместе с её нарушениями, идентификатором записи и штампом модели и промпта,
которые её создали, так что валидатор, отвергающий слишком много, станет
заметен:

```python
from sci_etl_core.claims import AsyncSqliteRejectionStore

rejections = AsyncSqliteRejectionStore("review/rejections.db")
extractor = AsyncLLMEntityExtractor(llm, "Extract galaxies as JSON.", schema=Galaxy, rejections=rejections)


async def review() -> None:
    for entry in await rejections.unresolved(limit=20):
        print(entry.record_id, entry.entity, [violation.message for violation in entry.violations])
        await rejections.resolve(entry.entry_id, "rejection upheld")
```

Повторное отклонение той же сущности в одном из следующих запусков сохраняет
одну запись вместе с её решением. Сбой хранилища отклонений приводит к неудаче
записи, которая повторяется при следующем запуске. *Отклонённая сущность* не
имеет отношения к *записи в карантине* — записи, которую пайплайн пропускает
после того, как она не удалась `max_attempts` раз.

## Экстракторы, учитывающие запись {#record-aware-extractors}

Пайплайн вызывает `extract_record(record, text)`. Его реализация по умолчанию
вызывает `extract(text)`, поэтому экстрактор, переопределяющий только
`extract`, работает без изменений. Экстрактор, которому нужна запись, например
`AsyncLLMClaimExtractor`, устанавливает `requires_record = True`, а его
`extract` вызывает `TypeError`. Экстрактор, оборачивающий другой, вызывает
`extract_record` внутреннего и копирует его `requires_record`:

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

`AsyncLLMEntityExtractor.prepare(text)` возвращает текст, который отправляется
модели, после удаления разметки и усечения, а `stamp` описывает модель,
промпт, схему и релиз библиотеки, стоящие за его сущностями.
