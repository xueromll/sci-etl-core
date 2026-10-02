# الكيانات المنمّطة والتحقق

يُعيد `AsyncLLMEntityExtractor` الكائنات التي كتبها النموذج في صورة قواميس `dict`،
ما لم تصف الكيان بنموذج Pydantic. فمع `schema=` يُتحقق من كل كيان مقابل النموذج قبل
أن يغادر المستخرِج، ويُعيد المستخرِج نسخًا من النموذج:

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

## المخرجات المنظَّمة {#structured-output}

يطلب الطلب أن تطابق الإجابة كلها، أي قائمة الكيانات تحت `result_key`، مخطط JSON
Schema مبنيًا من النموذج؛ وتُعيده `entity_list_schema(Galaxy, "galaxies")`. ويرسله
`AsyncOpenAICompatibleClient(structured_output=True)` بوصفه تنسيق استجابة
`json_schema`. اترك `structured_output` معطّلًا لنقطة النهاية التي لا تدعم ذلك
التنسيق، مثل نقطة DeepSeek: عندئذ يخرج الطلب بوضع JSON، ويجب أن يظل الموجِّه يصف
الحقول، ويظل كل كيان يخضع للتحقق.

يحصل عميلك الخاص على المخرجات المنظَّمة بإعادة تعريف
`complete_structured(system_prompt, user_content, schema, timeout)`. ويستدعي التنفيذ
الافتراضي `complete_json`، فيعمل كل عميل مع الاستخراج المنمّط.

المخطط جزء من مفتاح الذاكرة المؤقتة للنموذج اللغوي، فتغيير صنف النموذج لا يقدّم أبدًا
إجابة مخزنة للصنف القديم؛ راجع
[التخزين المؤقت لاستجابات النموذج اللغوي](llm-caching.md).

## الرفض وأسبابه {#rejections-and-their-reasons}

يُرفض الكيان عندما يخفق في المخطط، أو عندما يرفضه `validator`. ويرى المدقّق الكيان
في صورة `dict`، بعد فحص المخطط. ويُسجَّل كل رفض بالمستوى `INFO` على المسجِّل
`sci_etl_core.llm.extraction_async` مع أسبابه:

```text
Entity rejected by validation: 'DF44' (ra_deg is 412, outside [0, 360])
```

تُعيد `RecordValidator.validate(entity)` كائن `ValidationResult` تسمّي كل مخالفة في
`violations` الخاصة به `code` و`field` و`severity` و`message`. يُبلغ
`NumericRangeValidator` عن `"out-of-range"` و`"not-a-number"`، ويُبلغ
`KeywordExclusionValidator` عن `"null-key"` و`"forbidden-keyword"`، ويُبلغ إخفاق
المخطط عن `"schema"`، ويجمع `CompositeValidator` مخالفات كل مدقّق يحويه. والمدقّق
الخاص بك الذي لا ينفّذ إلا `is_valid` يظل يعمل: تظهر حالات رفضه بوصفها
`"rejected"`. أعِد تعريف `validate` لتوضيح السبب:

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

المخالفة التي لها `severity="warning"` يُبلَّغ عنها لكنها لا ترفض الكيان.

## الاحتفاظ بالكيانات المرفوضة للمراجعة {#keeping-rejected-entities-for-review}

مرّر مخزن رفض، فيُحتفظ بكل كيان مرفوض مع مخالفاته ومعرّف سجله وختم النموذج والموجِّه
اللذين أنتجاه، فيصبح المدقّق الذي يرفض أكثر مما ينبغي ظاهرًا للعيان:

```python
from sci_etl_core.claims import AsyncSqliteRejectionStore

rejections = AsyncSqliteRejectionStore("review/rejections.db")
extractor = AsyncLLMEntityExtractor(llm, "Extract galaxies as JSON.", schema=Galaxy, rejections=rejections)


async def review() -> None:
    for entry in await rejections.unresolved(limit=20):
        print(entry.record_id, entry.entity, [violation.message for violation in entry.violations])
        await rejections.resolve(entry.entry_id, "rejection upheld")
```

رفض الكيان نفسه مرة أخرى في تشغيل لاحق يُبقي إدخالًا واحدًا مع قراره. وعطل مخزن الرفض
يُفشل السجل، فيُعاد في التشغيل التالي. ولا علاقة بين *الكيان المرفوض* و*السجل
المحجور*، وهو سجل يتخطاه خط المعالجة بعد أن يفشل `max_attempts` مرة.

## المستخرِجات المدركة للسجل {#record-aware-extractors}

يستدعي خط المعالجة `extract_record(record, text)`. ويستدعي تنفيذها الافتراضي
`extract(text)`، فيعمل المستخرِج الذي لا يعيد تعريف إلا `extract` دون تغيير. أما
المستخرِج الذي يحتاج إلى السجل، مثل `AsyncLLMClaimExtractor`، فيضبط
`requires_record = True`، وترفع `extract` الخاصة به `TypeError`. والمستخرِج الذي يغلّف
مستخرِجًا آخر يستدعي `extract_record` الخاصة بالداخلي وينسخ `requires_record` منه:

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

تُعيد `AsyncLLMEntityExtractor.prepare(text)` النص المرسل إلى النموذج بعد إزالة
الترميز والاقتطاع، ويصف `stamp` النموذج والموجِّه والمخطط وإصدار المكتبة التي تقف خلف
كياناته.
