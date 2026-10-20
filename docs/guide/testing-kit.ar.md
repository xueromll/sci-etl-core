# اختبار مكوّناتك

تحتوي `sci_etl_core.testing` على مجموعات اختبارات العقد: أصناف اختبار pytest
تتحقق من سلوك المكوّن وفق عقد صنفه الأساسي. ورِّث المجموعة الخاصة بمكوّنك،
وأضف تجهيزة (fixture) تبنيه، فيشغّل pytest كل اختبار في المجموعة على تنفيذك.
وتجتاز التنفيذات المضمَّنة المجموعات نفسها.

| المجموعة | تتحقق من | التنفيذات المضمَّنة التي تعمل عليها |
|----------|----------|--------------------------------------|
| `ExtractorContract` | `AsyncExtractor` | `AsyncArxivExtractor`، `AsyncPubMedExtractor`، `AsyncSemanticScholarExtractor`، `AsyncOpenAlexExtractor` |
| `StateManagerContract` | `AsyncStateManager` | `AsyncFileStateManager`، `AsyncSqliteStateManager` |
| `ExporterContract` | `AsyncExporter` | `AsyncJsonlExporter`، `AsyncCsvExporter`، `AsyncClaimStoreExporter` |
| `EmbeddingStoreContract` | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`، `AsyncSqliteEmbeddingStore` |

## التثبيت {#installing}

تحتاج المجموعات إلى pytest، الذي تثبّته الإضافة (extra) `testing`:

```bash
pip install "sci-etl-core[testing]"
```

لا تستورد أي وحدة أخرى في المكتبة pytest. الاختبارات دوال عادية تشغّل كل
سيناريو عبر `asyncio.run`، لذا لا حاجة إلى pytest-asyncio.

## كتابة اختبار عقد {#writing-a-contract-test}

ورِّث المجموعة في وحدة اختبار باسم يجمعه pytest، وأعطها التجهيزة التي
تطلبها. هنا يجتاز مدير حالة يحفظ حالته في الذاكرة `StateManagerContract`:

```python
import dataclasses

import pytest

from sci_etl_core import AsyncStateManager, PipelineMetadata
from sci_etl_core.testing import StateManagerContract


class MemoryStateManager(AsyncStateManager):
    def __init__(self) -> None:
        self._processed: set[str] = set()
        self._metadata = PipelineMetadata()

    async def load_processed_ids(self) -> set[str]:
        return set(self._processed)

    async def mark_processed(self, record_id: str) -> None:
        self._processed.add(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return dataclasses.replace(self._metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        self._metadata = dataclasses.replace(metadata)


class TestMemoryStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self):
        manager = MemoryStateManager()
        return lambda: manager
```

يشغّل `python -m pytest` الآن كل اختبار في المجموعة على `MemoryStateManager`.
ولا يُجمع صنف المجموعة نفسه، لأن اسمه لا يبدأ بـ `Test`.

تعيد التجهيزة مصنعًا: كائنًا قابلًا للاستدعاء بلا وسائط، يعيد في كل استدعاء
نسخة جديدة فوق التخزين نفسه، كما يفتحه كل تشغيل لخط المعالجة. وتستدعيه
المجموعة أكثر من مرة في الاختبار الواحد لتتحقق من أن ما حفظته نسخة تحمّله
النسخة التالية. والمكوّن الذي يحفظ حالته في الذاكرة، مثل المكوّن أعلاه، يعيد
النسخة نفسها في كل مرة. ويبدأ التخزين فارغًا في كل اختبار، فابنه من `tmp_path`
أو داخل التجهيزة. تستدعي المجموعة المصنع داخل حلقة أحداث عاملة، وتنهي كل نسخة
كما ينتهي التشغيل: يحفظ مدير الحالة حالته ثم يُغلق عبر `aclose()` إن كان يملكه،
ويُغلق المصدِّر أو المخزن المتجهي.

## التجهيزات {#fixtures}

| المجموعة | التجهيزات المطلوبة | التجهيزات الاختيارية |
|----------|--------------------|----------------------|
| `ExtractorContract` | `make_extractor` | `make_unavailable_extractor` |
| `StateManagerContract` | `make_state_manager` | `write_newer_schema` |
| `ExporterContract` | `make_exporter`، `read_exported` | `make_entities`، `write_newer_schema` |
| `EmbeddingStoreContract` | `make_store` | `write_newer_schema` |

- **`make_extractor` و`make_state_manager` و`make_exporter` و`make_store`**
  تعيد المصنع الموصوف أعلاه.
- **`read_exported`** تعيد كائنًا غير متزامن قابلًا للاستدعاء يأخذ معرّف سجل
  ويعيد الكيانات التي تحفظها الوجهة لذلك السجل، أو تسلسلًا فارغًا. تقارن
  المجموعة بين قراءتين، فأعد شكلًا يتساوى عند تطابق المحتوى.
- **`make_entities`** تعيد كائنًا قابلًا للاستدعاء يبني `count` من الكيانات
  المختلفة لسجل واحد. يبني الإعداد الافتراضي قواميس بالمفتاحين `name` و`value`؛
  أعد تعريفها حين يأخذ مصدِّرك كيانات أخرى، مثل الادعاءات.
- **`write_newer_schema`** تعيد كائنًا قابلًا للاستدعاء يكتب، في التخزين الذي
  يفتحه المصنع، ملفًا أو قاعدة بيانات بإصدار مخطط أحدث مما يدعمه مكوّنك.
  تستدعيه المجموعة قبل أن تنشئ أي نسخة، وتتوقع `SciEtlError`. ويعيد الإعداد
  الافتراضي `None`.
- **`make_unavailable_extractor`** تعيد مصنعًا لمستخرِج يجيب مصدره عن كل طلب
  بعطل من جهة الخادم، مثل الحالة `503`، دون انتظار بين محاولات الإعادة. تتوقع
  المجموعة `UpstreamError` بدلًا من صفحة فارغة. ويعيد الإعداد الافتراضي `None`.

وحين تعمل مجموعة مدير الحالة نفسها على مدير الحالة المضمَّن القائم على SQLite،
تتحقق أيضًا من رفض قاعدة بيانات من إصدار أحدث:

```python
import sqlite3
from contextlib import closing

import pytest

from sci_etl_core import AsyncSqliteStateManager
from sci_etl_core.testing import StateManagerContract


class TestSqliteStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: AsyncSqliteStateManager(tmp_path / "state.db")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        def write():
            with closing(sqlite3.connect(tmp_path / "state.db")) as connection:
                connection.execute("PRAGMA user_version = 99")

        return write
```

ويحتاج المصدِّر أيضًا إلى `read_exported`، التي تقرأ وجهته من جديد:

```python
import pytest

from sci_etl_core.exporters import AsyncJsonlExporter, read_jsonl_export
from sci_etl_core.testing import ExporterContract


class TestJsonlExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncJsonlExporter(tmp_path / "out.jsonl", fsync=False)

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            return read_jsonl_export(tmp_path / "out.jsonl").get(record_id, [])

        return read
```

## اختبار مستخرِج دون شبكة {#testing-an-extractor-offline}

لا تستخدم مجموعة المستخرِجات الشبكة أبدًا. قدّم القائمة من بديل (stub)، مثل
`httpx.AsyncClient` مبني على `httpx.MockTransport`، واجعله يجيب عن الطلب نفسه
بالطريقة نفسها في كل مرة. يجب أن تضم القائمة صفحتين على الأقل لاستعلام
المجموعة، وأن تنتهي خلال `max_pages` صفحة. اضبط سمات الصنف هذه في صنفك الفرعي
بما يناسب مصدرك:

| السمة | القيمة الافتراضية | المعنى |
|-------|-------------------|--------|
| `query` | `"contract"` | الاستعلام الذي يسرده كل اختبار |
| `page_size` | `2` | حجم الصفحة الذي يطلبه كل اختبار |
| `max_pages` | `50` | أقصى عدد من الصفحات يجب أن تنتهي القائمة خلاله |

## القدرات الاختيارية والتخطي {#optional-capabilities-and-skips}

يُتخطّى الاختبار الذي يتحقق من قدرة اختيارية، مع ذكر السبب، حين يفتقر مكوّنك
إليها:

- **مديرو الحالة:** المحاولات الفاشلة، حين يُبقي `record_failure` على الإعداد
  الافتراضي الذي لا يتتبع شيئًا؛ و`forget`، حين لا يكون مدير الحالة
  `Forgetting`؛ وإعادة الاستخدام بعد `aclose()`، حين لا يملك `aclose`.
- **المصدِّرات:** قراءة ما كُتب قبل `flush`، حين تكون `durable_writes` مساوية
  لـ `False`.
- **المخازن المتجهية:** `iter_records`، حين يُبقي المخزن على الإعداد الافتراضي
  الذي يرفع `NotImplementedError`.
- **المستخرِجات:** اختبار الإزاحات، حين لا يكون المستخرِج `OffsetListing`؛
  واختبار المصدر غير المتاح، حين تعيد `make_unavailable_extractor` القيمة `None`.
- **مديرو الحالة والمصدِّرات والمخازن المتجهية:** اختبار إصدار المخطط، حين تعيد
  `write_newer_schema` القيمة `None`.

## ما الذي تتحقق منه المجموعات {#what-the-suites-check}

- **`ExtractorContract`:** الصفحة الأولى `ListingPage` سليمة البنية فيها سجلات
  ومؤشر تالٍ؛ ويعيد المؤشر التالي الصفحة نفسها مرة أخرى، ومن مستخرِج جديد
  أيضًا، كما يطلبها تشغيل مستأنَف؛ وتتبّع المؤشرات التالية ينهي القائمة، ولا
  تملك الصفحة المقتطعة مؤشرًا تاليًا؛ وفي `OffsetListing` تكون الإزاحة 0 هي
  الصفحة الأولى، ويكون عدد مدخلات الصفحة الأولى هو إزاحة الصفحة الثانية؛ وتعيد
  `fetch_full_text` سلسلة نصية؛ ويرفع المصدر الذي يتعذر الوصول إليه
  `UpstreamError`.
- **`StateManagerContract`:** التخزين الجديد فارغ؛ والمعرّفات المعالَجة
  والبيانات الوصفية المحفوظة والمحاولات الفاشلة تصل إلى النسخة التالية؛ وتُحفظ
  كل العلامات المتزامنة؛ وتختم `save_metadata` وقت التشغيل؛ وتمسح
  `mark_processed` محاولات السجل؛ وتمسح `forget` العلامات والمحاولات وتُبقي على
  المؤشر؛ وتُرفض الحالة ذات إصدار المخطط الأحدث؛ ويعمل مدير الحالة من جديد بعد
  `aclose()`.
- **`ExporterContract`:** يصدّر التشغيل كيانات كل سجل؛ وتكرار الكتابة، بالتزامن
  أو في التشغيل نفسه أو في تشغيل لاحق، يترك ما تركته كتابة واحدة؛ والسجل
  المكتوب بلا كيانات لا يحفظ أيًّا منها؛ وينجح التشغيل الذي لا يكتب شيئًا؛
  ويعمل المصدِّر من جديد بعد `aclose()`؛ ومع `durable_writes = True` يمكن قراءة
  ما كُتب قبل `flush`؛ وتُرفض الوجهة ذات إصدار المخطط الأحدث.
- **`EmbeddingStoreContract`:** المخزن الجديد فارغ؛ والمقطع المضاف من جديد
  بمعرّف سجله وفهرسه يحل محل القديم؛ والمقاطع تصل إلى النسخة التالية؛ وتأتي
  النتائج من الأفضل إلى الأسوأ بحسب تشابه جيب التمام، وتراعي `top_k`
  و`min_score` و`exclude_record_id`؛ والمتجه الذي يحوي NaN لا يطابق أبدًا؛
  ولا تترك `delete_record` و`replace_record` أي مقطع قديم للسجل؛ وتُخرج
  `iter_records` المقاطع بالترتيب؛ ويعمل المخزن من جديد بعد `aclose()`؛ ويُرفض
  التخزين ذو إصدار المخطط الأحدث.

تتحقق المجموعات من السلوك عبر الدوال العامة وحدها. يسرد
[جدول العقود](../project/contributing.md#adding-a-new-component) ما يجب أن
يفعله كل مكوّن، ويوثّق [مرجع واجهة الاختبار البرمجية](../reference/testing.md)
كل مجموعة.
