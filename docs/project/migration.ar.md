# دليل الترحيل

يسرد هذا الدليل ما يتغير في الشيفرة القائمة عند الانتقال إلى إصدار جديد من `sci-etl-core`،
بدءًا بأحدث إصدار. ويسرد [CHANGELOG.md](changelog.md) كل تغيير، بما في ذلك الإضافات التي لا
تتطلب أي إجراء.

ثبّت نطاقًا من الإصدارات الفرعية، مثل `sci-etl-core>=0.6.0,<0.7`، وارفع الحد الأعلى بعد أن
تنجح اختباراتك على الإصدار الفرعي التالي. وعند الانتقال من إصدار فرعي إلى إصدار لاحق، طبّق كل
قسم بينهما، بدءًا بالأقدم.

لنقل خط معالجة بحثي قائم إلى المكتبة للمرة الأولى، اتبع المثال التطبيقي في
[ترحيل خط معالجة](https://xueromll.github.io/sci-etl-core/latest/guide/migrating-a-pipeline/).

- [الترقية إلى 0.6](#upgrading-to-06)
- [الترقية إلى 0.5.1](#upgrading-to-051)
- [الترقية إلى 0.5](#upgrading-to-05)
- [الترقية إلى 0.4](#upgrading-to-04)
- [الترقية إلى 0.3](#upgrading-to-03)

---

## الترقية إلى 0.6 {#upgrading-to-06}

يغيّر 0.6 عقد البيانات: ما يُعيده مستخرِج الكيانات، وكيف يتلقى المصدِّر الكيانات، وكيف تسجّل
المكتبة، وما يحويه التثبيت الأساسي. وهو آخر إصدار قبل 1.0 يكسر عقدًا قائمًا. اطلب الإصدار
الفرعي الجديد مع الإضافات التي تستخدمها:

```text
sci-etl-core[config,async,arxiv,llm,pdf,processors]>=0.6.0,<0.7
```

تُفتح ملفات الحالة وقواعد بياناتها، والذاكرات المؤقتة للنموذج اللغوي، ومخازن التضمينات،
والفهارس النصية التي كتبها 0.5 دون تغيير. وتظل إجابات النموذج اللغوي المخزنة صالحة: فالطلب الذي
لا مخطط له له مفتاح الذاكرة المؤقتة نفسه الذي كان له في 0.5.1.

### ثبّت الإضافات التي تستوردها {#install-the-extras-you-import}

صار التثبيت الأساسي لا يتطلب إلا Pydantic. فانتقل PyYAML وpython-dotenv إلى الإضافة `config`،
وBeautiful Soup وlxml إلى `arxiv` و`html` و`xml`، وpandas إلى `processors`. ولم تعد أي إضافة
تثبّت `aiofiles` أو `aiosqlite`. واستيراد مكوّن تنقصه إضافته يرفع `ModuleNotFoundError` مع اسم
الحزمة:

| تستخدم | أضف الإضافة |
|--------|-------------|
| `load_config`، `load_config_async`، `load_yaml` | `config` |
| `AsyncArxivExtractor` | `async`، `arxiv` |
| `AsyncPubMedExtractor` | `async`، `xml` |
| `JatsXmlParser`، `DocxParser` | `xml` |
| `HtmlTextParser`، أو `AsyncLLMEntityExtractor` على نص كامل يبدأ بترميز | `html` |
| أي شيء في `sci_etl_core.processors` عدا المدقّقات | `processors` |

لا يزال `full` يثبّت كل المكوّنات المضمّنة عدا التضمينات المحلية.

### لا تُقرأ ملفات `.env` إلا عند الطلب {#env-files-are-read-only-when-asked}

لم تعد `load_config` و`load_config_async` تبحثان عن ملف `.env` ضمنيًا. مرّر الملف، أو اطلب
البحث:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), load_env=True)
config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
```

ودون أيٍّ منهما، يجب أن يكون مفتاح الواجهة البرمجية موجودًا أصلًا في البيئة.

### تأخذ المصدِّرات السجل ووجهتها {#exporters-take-the-record-and-their-destination}

استُبدلت `AsyncExporter.export(data, destination)` بدورة حياة. يستدعي خط المعالجة `open()` قبل
أول طلب للقائمة، و`write(record, entities)` لكل سجل معالَج بما فيه السجل الذي لا كيانات له،
و`flush()` بعد كل صفحة، و`aclose()` عند انتهاء التشغيل أيًّا كانت طريقة انتهائه. ويأخذ المصدِّر
وجهته عند إنشائه، فاختفى الوسيط `destination=` من خط المعالجة:

```python
from sci_etl_core import AsyncCsvExporter, AsyncETLPipeline

pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager,
)
```

أُزيل `AsyncCsvUpsertExporter`. وبديله `AsyncCsvExporter` لا يدمج الصفوف: فهو يكتب صفًا لكل
كيان مع `record_id` الخاص بالورقة التي جاء منها، ويحتفظ بالمفاتيح الأخرى في عمود `extra`، ويكتب
القيم دون تغيير، فلا تُقتطع القيمة ولا تُحوَّل ولا تضيع أبدًا، وورقتان تُبلغان عن جرم واحد تعطيان
صفين. ادمج في المعالجة اللاحقة، حيث يكون الاختيار صريحًا:

```python
import pandas as pd

from sci_etl_core.processors import DeduplicationStep, DefaultKeyNormalizer, NormalizationStep, ProcessorChain

raw = pd.read_csv("results.csv", dtype={"record_id": str, "name": str})
one_row_per_name = ProcessorChain(
    [NormalizationStep("name", DefaultKeyNormalizer()), DeduplicationStep("_norm_key")]
).process(raw)
```

يُكتب ملف CSV عند انتهاء التشغيل؛ وأثناء التشغيل تذهب الصفحات إلى `results.csv.journal`، الذي
يعيد التشغيل التالي تطبيقه إن انهار تشغيل ما. أضف `*.journal` إلى `.gitignore` بجوار ملف
مخرجاتك. وترويسة الملف الجديد هي `record_id` وأعمدتك و`extra`، فابدأ ملفًا جديدًا بدلًا من
توجيه المصدِّر إلى ملف كتبه `AsyncCsvUpsertExporter`؛ فالمصدِّر يرفض الملف ذا الترويسة المختلفة.
أما `AsyncJsonlExporter` فيكتب سطر JSON واحدًا لكل سجل بدلًا من ذلك.

ينفّذ المصدِّر المخصص `write`، وإن كان يخزّن مؤقتًا فإنه يضبط `durable_writes = False` وينفّذ
`flush`:

```python
from sci_etl_core import AsyncExporter


class DatabaseExporter(AsyncExporter):
    def __init__(self, database):
        self.database = database

    async def write(self, record, entities):
        await self.database.replace_rows(record.record_id, list(entities))
```

يجب أن تكون `write` متساوية القوة، لأن الانهيار قد يكرر سجلًا، وينبغي للسجل الذي لا كيانات له أن
يمسح ما خزّنته كتابة سابقة. ولا يُعلَّم السجل معالَجًا إلا بعد أن تصبح كياناته دائمة: مباشرة بعد
`write`، أو بعد `flush` الصفحة حين تكون `durable_writes` مساوية لـ `False`. وعطل `write` يُفشل
السجل ويحتسب محاولة واحدة، وعطل `flush` يترك السجلات المكتوبة في الصفحة دون تسوية دون احتساب
محاولة، وعطل `open` يُجهض التشغيل قبل أي طلب. ويرقّم
[دلالات التشغيل](https://xueromll.github.io/sci-etl-core/latest/guide/run-semantics/) هذه
القواعد من R20 إلى R23.

أُزيل `AsyncSqlTableExporter` و`AsyncPlotly3DExporter`؛ استخدم `SqlTableSink` و`Plotly3DSink`
من `sci_etl_core.processors.sinks`، كما يوضح [مصارف الجداول](#table-sinks). ويُستورد
`ScatterPlotConfig` من `sci_etl_core.processors`.

### مستخرِجات الكيانات منمّطة ومدركة للسجل {#entity-extractors-are-typed-and-record-aware}

`AsyncEntityExtractor` عام في نوع كيانه، ويستدعي خط المعالجة `extract_record(record, text)`،
التي يستدعي تنفيذها الافتراضي `extract(text)`. والمستخرِج الذي لا يعيد تعريف إلا `extract` لا
يحتاج إلى تغيير. وينبغي للمغلّف المحيط بمستخرِج آخر أن يفوّض `extract_record` أيضًا، كي يظل يعمل
حول مستخرِج يحتاج إلى السجل، مثل `AsyncLLMClaimExtractor`:

```python
from sci_etl_core import AsyncEntityExtractor


class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(self, inner, validator):
        self.inner = inner
        self.validator = validator
        self.requires_record = inner.requires_record

    async def extract(self, text):
        return [entity for entity in await self.inner.extract(text) if self.validator.is_valid(entity)]

    async def extract_record(self, record, text):
        entities = await self.inner.extract_record(record, text)
        return [entity for entity in entities if self.validator.is_valid(entity)]
```

لم يعد مثل هذا المغلّف لازمًا عادة: فـ `AsyncLLMEntityExtractor` يأخذ `validator`، ويسجّل كل رفض
مع أسبابه، ويمكنه الاحتفاظ بالكيانات المرفوضة في مخزن رفض. وكل الوسائط بعد `system_prompt` صارت
لا تُمرَّر إلا بأسمائها.

للتحقق من الكيانات مقابل نموذج Pydantic وتلقي نسخ من النموذج، مرّر `schema=`؛ راجع
[الكيانات المنمّطة والتحقق](https://xueromll.github.io/sci-etl-core/latest/guide/typed-entities/).
وينبغي لأي `AsyncLLMClient` مخصص يغلّف عميلًا آخر أن يمرر `complete_structured` وأن يقبل
`schema=` في `invalidate`.

### المدقّقات تذكر السبب {#validators-say-why}

تُعيد `RecordValidator.validate(entity)` كائن `ValidationResult` مؤلفًا من كائنات `Violation`.
والمدقّق الذي لا ينفّذ إلا `is_valid` يظل يعمل. أما الذي يحسب السبب أصلًا، كأن تكون له طريقة
`rejection_reason`، فيمكنه إعادة تعريف `validate` بدلًا من ذلك، فيصل السبب إلى السجل وإلى مخزن
الرفض:

```python
from sci_etl_core.processors import RecordValidator, ValidationResult, Violation


class RangeValidator(RecordValidator):
    def is_valid(self, record):
        return self.validate(record).ok

    def validate(self, record):
        radius = record.get("radius_kpc")
        if radius is not None and not 0.1 <= float(radius) <= 20.0:
            violation = Violation(code="out-of-range", field="radius_kpc", severity="error", message=f"radius {radius} kpc")
            return ValidationResult(violations=(violation,))
        return ValidationResult()
```

### يمر التسجيل عبر الوحدة `logging` {#logging-goes-through-the-logging-module}

أُزيلت كل وسائط `logger=`: من `AsyncETLPipeline` و`ETLPipeline` والمستخرِجات الأربعة
و`AsyncLLMEntityExtractor` و`CachingLLMClient` و`AsyncCompositeIngestor` و`AsyncHybridSearcher`
و`ShutdownSignal`. وأُزيلت `configure_logging` و`sci_etl_core.log_utils`، وكذلك
`AsyncETLPipeline.log`. وتسجّل كل وحدة تحت اسمها الخاص أسفل المسجِّل `sci_etl_core`، فاضبط
التسجيل في التطبيق:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler("output/pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
```

تحتفظ الرسائل بصياغتها. وكان `CachingLLMClient` يأخذ `logger` وسيطًا موضعيًا رابعًا؛ والاستدعاء
الذي كان يمرره موضعيًا يفشل الآن بـ `TypeError`.

### الأسماء المُزالة {#removed-names}

أُزيلت إهمالات 0.5: العقود المتزامنة `Extractor` و`StateManager` و`Exporter` و`LLMClient`
و`RelevanceFilter` و`EntityExtractor`؛ ومحوّلاتها `SyncExtractorAdapter`
و`SyncRelevanceFilterAdapter` و`SyncEntityExtractorAdapter` و`SyncExporterAdapter`
و`SyncStateManagerAdapter` و`SyncLLMClientAdapter`؛ و`LegacyExtractorAdapter`؛
و`AsyncExporter.export` والوسيط `destination`؛ و`AsyncCsvUpsertExporter`
و`AsyncSqlTableExporter` و`AsyncPlotly3DExporter`؛ و`configure_logging`. نفّذ العقود غير
المتزامنة، مع تشغيل العمل المتزامن داخلها بـ `asyncio.to_thread`. ويبقى `ETLPipeline`، ويشغّل خط
المعالجة غير المتزامن من شيفرة متزامنة كما من قبل.

منذ 0.6 يظل الاسم المهمل يعمل لإصدارين فرعيين على الأقل قبل إزالته.

## الترقية إلى 0.5.1 {#upgrading-to-051}

لا يكسر 0.5.1 أي استدعاء قائم، لكن ثلاث نتائج من النموذج اللغوي كانت تسوّي السجل صارت الآن
تُفشله. فيبقى السجل دون تعليم، وتُحتسب محاولته ضمن `max_attempts`، ويعيده التشغيل التالي:

- **إكمال فارغ.** ترفع `AsyncOpenAICompatibleClient.complete_json` الاستثناء `LLMError` بدلًا من
  إعادة `{}`.
- **استجابة بلا قائمة كيانات.** ترفع `AsyncLLMEntityExtractor.extract` الاستثناء `LLMError` حين
  تكون الاستجابة فارغة، أو فيها عدة مفاتيح ليس أيٌّ منها `result_key`، بدلًا من إعادة `[]`.
- **عطل في الصلة مع `default_on_error=False`.** يرفع `AsyncLLMRelevanceFilter`
  و`AsyncEmbeddingRelevanceFilter` استثناءً بدلًا من قراءة العطل على أنه "غير ذي صلة"، وهو ما كان
  يعلّم السجل معالَجًا إلى الأبد.

إن كان نموذجك يجيب أحيانًا بكائن فارغ، أو بقائمة الكيانات تحت مفتاح آخر، فإن هذه السجلات تفشل
الآن وتوضع في الحجر بعد `max_attempts` تشغيلًا. سمِّ `result_key` في الموجِّه. وينبغي لأي
`AsyncLLMClient` مخصص أن يرفع `LLMError` للاستجابة التي يعجز عن قراءتها بدلًا من إعادة `{}`.

تبقى السجلات التي علّمتها الإصدارات السابقة معالَجة بهذه الطريقة معلَّمة؛ ولا يعود إليها إلا تشغيل
بحالة جديدة.

وتتغير الذاكرة المؤقتة للنموذج اللغوي أيضًا:

- **تُخفق كل استجابة مخزنة مرة واحدة.** صار مفتاح الذاكرة المؤقتة يتضمن `base_url` لنقطة
  النهاية ودرجة الحرارة وتنسيق الاستجابة، فيستدعي أول تشغيل بعد الترقية النموذج اللغوي لكل طلب.
  ولا تُقرأ الإدخالات التي كتبتها الإصدارات السابقة مرة أخرى أبدًا؛ احذف ملف الذاكرة المؤقتة، أو
  استدعِ `clear()`، لاستعادة المساحة. ولم يعد يلزم اسم نموذج يرمّز درجة الحرارة، مثل
  `"gpt-4o-mini@t0.2"`.
- **تُزال الاستجابات المرفوضة.** يستدعي `AsyncLLMEntityExtractor` و`AsyncLLMRelevanceFilter`
  الدالة `invalidate` على عميلهما حين يرفضان استجابة، فيحذفها `CachingLLMClient`، لتصل إعادة
  المحاولة إلى النموذج. وينبغي لأي `AsyncLLMResponseCache` مخصص أن ينفّذ `delete`. وينبغي لأي
  عميل مخصص يغلّف عميلًا آخر أن يمرر إليه `invalidate`.

## الترقية إلى 0.5 {#upgrading-to-05}

يغيّر 0.5 طريقة تنقل المستخرِجات بين الصفحات، وما تحفظه الحالة، وطريقة إنشاء خط المعالجة. أما
الكيانات والمصدِّرات فتتغير في 0.6. اطلب الإصدار الفرعي الجديد وبايثون 3.11:

```text
sci-etl-core[async,llm,pdf]>=0.5.0,<0.6
```

لا تحتاج الحالة التي كتبها 0.4 إلى أي تحويل. يرقّي `AsyncSqliteStateManager` قاعدة بياناته في
مكانها، ويقرأ `AsyncFileStateManager` ملف البيانات الوصفية القديم ويعيد كتابته بالتنسيق الجديد
عند الحفظ التالي. وفي الحالتين تصبح الإزاحة المحفوظة هي المؤشر، فيستأنف التشغيل التالي من حيث
توقف السابق.

### تُعيد المستخرِجات صفحات محلَّلة {#extractors-return-parsed-pages}

استُبدلت `search` و`parse_listing` بدالة واحدة `fetch_page` تُعيد `ListingPage`. وصار خط
المعالجة يتخطى السجلات المعالَجة بنفسه، فيُعيد المستخرِج كل مدخل يستطيع قراءته. والمصدر الذي
يتنقل بالإزاحة ينفّذ `cursor_for_offset` أيضًا، مما يجعله `OffsetListing`.

قبل:

```python
class MyExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return await self._client.get_page(query, start_index, max_results)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        entries = parse(raw_listing)
        return [entry for entry in entries if entry.record_id not in seen_ids], len(entries)
```

بعد:

```python
class MyExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = int(cursor or 0)
        entries = parse(await self._client.get_page(query, offset, page_size))
        return ListingPage(
            records=tuple(entries),
            entries=len(entries),
            next_cursor=str(offset + len(entries)) if entries else None,
        )
```

المصدر ذو رموز المتابعة المبهمة يُعيد الرمز بوصفه `next_cursor` ويُغفل `cursor_for_offset`.
والمصدر الذي يتوقف عند حد نتائجه الخاص يُعيد `truncated=True` و`next_cursor=None` في الصفحة التي
تبلغه. وإلى أن يُنقل المستخرِج، يشغّله `LegacyExtractorAdapter(MyOldExtractor())` دون تغيير في
0.5.x، مع `DeprecationWarning`؛ ويُزيل 0.6 هذا المحوّل.

المغلّف الذي يمرر الاستدعاءات إلى مستخرِج آخر، كمسجِّل للتقدم، يمرر `fetch_page`، و
`cursor_for_offset` أيضًا حين يغلّف `OffsetListing`:

```python
class LoggingExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return self._inner.cursor_for_offset(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self._log(f"Fetching listing page at cursor {cursor or 'start'}")
        return await self._inner.fetch_page(query, cursor, page_size)
```

يحتاج `newest_first=True` و`start_index` الأكبر من 0 إلى `OffsetListing`، ويرفعان `ValueError`
قبل أي طلب في غير ذلك. و`AsyncArxivExtractor` و`AsyncPubMedExtractor`
و`AsyncSemanticScholarExtractor` من نوع `OffsetListing`. أما `AsyncOpenAlexExtractor` فصار
يتنقل بمؤشرات OpenAlex، فيتجاوز أول 10,000 عمل لكنه لم يعد يدعم `newest_first`؛ ويعيد أول تشغيل
له على 0.5 بدء القائمة مرة واحدة من الصفحة الأولى، لأن الإزاحة التي حفظها 0.4 ليست مؤشر
OpenAlex.

### ما تحفظه الحالة {#what-the-state-saves}

يحل `PipelineMetadata.cursor` محل `last_start_index`. والشيفرة التي تقرأ الموضع المحفوظ تقرأ
المؤشر، وهو إزاحة عشرية في حالة `OffsetListing`:

```python
metadata = await state.load_metadata()
saved_offset = int(metadata.cursor or 0)
```

تكتسب أحداث التقدم الحقل `cursor`. وتظل `RunStarted.start_index` و`PageFetched.offset`
و`PageFinished.offset` تحمل إزاحة القائمة في حالة `OffsetListing`، وتكون `None` لأي مستخرِج
آخر.

### القوائم المحدودة تبدأ من جديد {#capped-listings-start-over}

تتوقف PubMed عند 9,999 نتيجة، وSemantic Scholar عند 1,000. وفي 0.4 كان التشغيل الذي يبلغ الحد
يحفظ الحد إزاحةً له، فينتهي كل تشغيل لاحق هناك فورًا. أما في 0.5 فالصفحة التي تبلغ الحد تُنهي
التشغيل بالحالة `"completed"`، وتُبلغ عن ذلك `RunMetrics.listing_truncated`، ويُعاد ضبط المؤشر
المحفوظ، فيتصفح التشغيل التالي النتائج المتاحة من جديد: تُتخطى السجلات المعالَجة حسب المعرّف،
فلا تكلّف إعادة المسح إلا طلبات قوائم، لا استدعاءات للنموذج اللغوي. ضيّق الاستعلام، مثلًا حسب
التاريخ، لتجنب إعادة المسح.

### توضع السجلات التي تظل تفشل في الحجر {#records-that-keep-failing-are-quarantined}

السجل الذي يفشل في 3 تشغيلات، كل مرة في صفحة عولج فيها سجل آخر، يُتخطى بوصفه محجورًا بدءًا من
التشغيل التالي ويُحتسب في `RunMetrics.quarantined`. ولا تُحتسب أبدًا الإخفاقات في صفحة لم يُعالَج
فيها شيء، كما يحدث أثناء انقطاع الخدمة أو مع مفتاح واجهة برمجية مرفوض. وللإبقاء على سلوك 0.4،
بإعادة كل سجل فاشل إلى الأبد:

```python
await pipeline.run(query, page_size=100, total_limit=500, max_attempts=None)
```

يظل مدير الحالة الخاص بطرف ثالث يعمل دون تغيير: فللدالتين الجديدتين `record_failure`
و`failure_counts` تنفيذات افتراضية لا تتتبّع شيئًا، فلا يحجر أي سجل أبدًا.

### الوسائط المسمّاة {#keyword-arguments}

يأخذ `AsyncETLPipeline` و`ETLPipeline` المكوّنات المتعاونة الخمسة موضعيًا أو بأسمائها، وكل ما
عداها بالاسم فقط. وتأخذ `run` الوسيط `query` ثم وسائط مسمّاة فقط، واختفى `max_records=`:

```python
pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    exporter,
    state_manager,
    destination="results.csv",
    max_concurrency=4,
)
await pipeline.run("all:galaxy", page_size=50, total_limit=200)
```

`RawRecord` و`PipelineMetadata` و`TokenUsage` و`RunMetrics` والأحداث لا تقبل إلا الوسائط
المسمّاة، فيصبح `RawRecord("id", "title", "abstract")` هو
`RawRecord(record_id="id", title="title", abstract="abstract")`.

### أقسام إعداد صارمة {#strict-config-sections}

صار المفتاح الذي لا يعلنه قسم مضمَّن يُفشل التحقق ويُسمّى في `ConfigurationError`، فلم يعد خطأ
إملائي مثل `search.bm25.titel` أو المفتاح القديم `pipeline.max_records` يمر بصمت. أعِد تسمية
`pipeline.max_records` إلى `total_limit` و`pipeline.max_workers` إلى `max_concurrency`. والتطبيق
الذي يجب أن يقبل مفاتيح مجهولة في الوقت الحالي يُلغي الصرامة في صنف إعداده، ويُبلَّغ عن كل مفتاح
محذوف بتحذير `UserWarning`:

```python
class AppConfig(BaseAppConfig):
    strict_sections = False
```

تُحفظ الأقسام العليا التي يعرّفها التطبيق كما من قبل.

### مصارف الجداول {#table-sinks}

كان `AsyncSqlTableExporter` و`AsyncPlotly3DExporter` يأخذان `DataFrame` ولم يكن ممكنًا تشغيلهما
في خط المعالجة. وبديلاهما مصرفان متزامنان لمخرجات المعالجة اللاحقة:

```python
from sci_etl_core.processors.sinks import Plotly3DSink, ScatterPlotConfig, SqlTableSink

catalogue = chain.process(raw_table)
SqlTableSink("sqlite:///catalogue.db", "galaxies", if_exists="replace").write(catalogue)
Plotly3DSink(ScatterPlotConfig("x", "y", "z", color_column="size"), "catalogue.html").write(catalogue)
```

### إهمالات بلا بديل قبل 0.6 {#deprecations-with-no-replacement-before-06}

تظل هذه الأسماء تعمل في 0.5.x وتُصدر `PendingDeprecationWarning` لا `DeprecationWarning`، لأن
بدائلها تصدر في 0.6 ولا يوجد ما يُغيَّر بعد: الوسيط `destination`، و`AsyncExporter.export`
و`AsyncCsvUpsertExporter` (اللذان تستبدلهما دورة حياة المصدِّر و`AsyncCsvExporter`)، وكل وسيط
`logger=` و`configure_logging` (اللذان تستبدلهما الوحدة القياسية `logging`). ولذلك تظل مجموعة
الاختبارات التي تُشغَّل مع `-W error::DeprecationWarning` تنجح ما دامت تستخدمها.

أما العقود المتزامنة ومحوّلاتها `Sync*Adapter`، و`LegacyExtractorAdapter`، ومصدِّرا الجداول،
فتُصدر `DeprecationWarning`، لأن بدائلها موجودة في 0.5؛ انتقل إلى العقود غير المتزامنة، التي
ينفّذها كل مكوّن أصلًا، وإلى `fetch_page`، وإلى مصارف الجداول.

أُزيلت `build_retrying_session`، ولم تعد الإضافة `full` تثبّت `requests`.

## الترقية إلى 0.4 {#upgrading-to-04}

```text
sci-etl-core[async]>=0.4.0,<0.5
```

يضيف 0.4 مصادر ومحلِّلات جديدة، والتخزين المؤقت لاستجابات النموذج اللغوي، والإيقاف السلس،
وأحداث التقدم، ومحدِّدات المعدل، وميزات البحث. وتؤثر هذه التغييرات في الشيفرة القائمة:

- **إعدادات خط المعالجة المعاد تسميتها.** صار `pipeline.max_records` هو `total_limit`،
  و`pipeline.max_workers` هو `max_concurrency`. وتظل مفاتيح YAML القديمة والخاصيتان
  `PipelineConfig.max_records` و`max_workers` تعمل حتى 0.5، مع `DeprecationWarning`، وأُهمل
  `run(max_records=)` بالطريقة نفسها. أعِد تسمية المفتاحين في ملف إعدادك.
- **مزيد من إعدادات خط المعالجة.** صار لـ `PipelineConfig` الحقول `page_size` و`search_delay`
  و`newest_first`. ويمكن حذف الصنف الفرعي الذي لم يكن يضيف إلا هذه الحقول.
- **التحقق دون مغلّف.** يأخذ `AsyncLLMEntityExtractor` الوسائط `validator=` و`logger=`
  و`label_field=`، ويسجّل كل كيان يحذفه بوصفه `Entity rejected by validation: <label>`. ويمكن
  حذف المستخرِج الذي كان يغلّفه لمجرد تطبيق `RecordValidator`.
- **المكوّنات من الإعداد.** تقرأ `AsyncArxivExtractor.from_config`
  و`AsyncOpenAICompatibleClient.from_config` و`AsyncETLPipeline.from_config` الأقسام `http`
  و`llm` و`pipeline`، وتحل `config.http.build_client()` محل `build_async_client`، وتُعيد
  `config.pipeline.run_arguments()` وسائط `run()`، فلم يعد يلزم نسخ الإعدادات يدويًا إلى
  المُنشئات.
- **الاستئناف من الأحدث.** يلتقط `run(newest_first=True)` إرسالات arXiv الجديدة دون إعادة المسح
  الكاملة التي يكلّفها `start_index=0`، ويحفظ رأس القائمة في ملف البيانات الوصفية بجوار
  `last_start_index`. ولا يمكن جمع `start_index` معه.
- **الرسوم.** يأخذ `ScatterPlotConfig` الوسائط `hover_data_columns` و`hover_template`
  و`color_continuous_scale` و`color_range`، التي تغطي نص التلميح المخصص ونطاقات الألوان الثابتة
  التي كانت تتطلب بناء الشكل يدويًا.
- **الحصر وتخطيط الجدول.** يحصر `ValueClipStep` قيم الأعمدة أثناء المعالجة اللاحقة، ويرتّب
  `TableLayoutStep` الصفوف والأعمدة، بدلًا من معالِجات خاصة بالمشروع كانت تؤدي أيًّا من الأمرين.
- **البحث من الذاكرة التي لديك أصلًا.** يستطيع المشروع الذي خزّن مقاطع في
  `AsyncSqliteEmbeddingStore` أن يبني منها فهرسًا نصيًا بـ `backfill_text_index` بدلًا من جلب كل
  ورقة من جديد.
- **مقتطفات للنتائج الدلالية.** صار `FusedHit` الذي لم يجده إلا الفرع الدلالي يحمل مقتطفًا من
  أفضل مقاطعه، حيث كان `snippet` فيه فارغًا من قبل. وينبغي للواجهة التي كانت تعرض الملخص كلما
  كان `snippet` فارغًا أن تفحص `lexical_rank is None` بدلًا من ذلك.
- **أداة `requests` المساعدة المهملة.** تُصدر `build_retrying_session` تحذيرًا وستُزال في 0.5،
  مع `requests` في الإضافة `full`.

## الترقية إلى 0.3 {#upgrading-to-03}

```text
sci-etl-core[async]>=0.3.0,<0.4
```

يضيف 0.3 البحث المحلي ورسوم الاستكشاف البيانية. وتؤثر هذه التغييرات في الشيفرة القائمة:

- **تحمل سجلات arXiv بيانات وصفية.** صارت `RawRecord.metadata` تحوي `categories` و`authors`
  و`published` و`year` بدلًا من أن تبقى فارغة. وترى شيفرتك التي تقرأ السجلات، بما فيها
  الاختبارات التي تقارن `metadata == {}`، المفاتيح الجديدة. ولم تتغير البيانات الوصفية المخزنة مع
  مقاطع التضمين.
- **يقبل `memory_ingestor` أي `MemoryIngestor`.** يعمل `AsyncChunkIngestor` تمامًا كما من قبل.
  ويمكن توسيع أي تلميح نوع في شيفرتك يسمّي `AsyncChunkIngestor` لهذا الوسيط إلى
  `MemoryIngestor`.
- **البحث اختياري.** لا يتغير شيء في خط معالجة لا يمرر فهرسًا نصيًا. ولإضافة واحد، مرّر
  `AsyncSearchIndexer`، أو `AsyncCompositeIngestor` مع مستوعِب المقاطع أولًا، كما يوضح
  [البحث والاستكشاف المحليان](https://xueromll.github.io/sci-etl-core/latest/guide/search/).
  ويوضع `AsyncSqliteFts5Store` الخاص به في `closeables` مثل أي مخزن SQLite آخر.
- **صارت حالة SQLite أكثر أمانًا عند الإلغاء.** لم يعد `AsyncSqliteStateManager` يسمح لخيط
  العامل الخاص بعملية ملغاة بأن يتداخل مع العملية التالية. ولم يتغير `AsyncFileStateManager`.

أسئلة أو موضع خشن في ترقيتك؟ افتح
[مشكلة](https://github.com/xueromll/sci-etl-core/blob/master/.github/ISSUE_TEMPLATE/bug_report.md)،
ويسعدنا أن نساعد.
