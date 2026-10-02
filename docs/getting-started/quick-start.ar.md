# البدء السريع

يبحث هذا المثال في arXiv، ويسأل نموذجًا لغويًا عن الأوراق ذات الصلة، ويستخرج القياسات
من نصوصها الكاملة، ويكتبها في ملف CSV بصف واحد لكل قياس. يحتاج إلى الإضافات `async`
و`arxiv` و`llm` و`pdf`، ويقرأ مفتاح الواجهة البرمجية من متغير البيئة `LLM_API_KEY`،
فلا يظهر المفتاح أبدًا في الشيفرة المصدرية. ولتحميله من ملف `.env` بدلًا من ذلك، راجع
[الإعداد](configuration.md).

```python
import asyncio
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

RELEVANCE_PROMPT = (
    "Decide whether the paper reports measurements of galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "Extract every measured object from the paper. Reply with JSON: "
    '{"items": [{"name": "...", "value_a": 0.0, "value_b": 0.0}]}.'
)


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(
        api_key=os.environ["LLM_API_KEY"],
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(
            client=client,
            pdf_parser=PdfPlumberParser(),
            latex_parser=LatexTarballParser(),
        ),
        relevance_filter=AsyncLLMRelevanceFilter(
            llm_client=llm, system_prompt=RELEVANCE_PROMPT
        ),
        entity_extractor=AsyncLLMEntityExtractor(
            llm_client=llm, system_prompt=EXTRACTION_PROMPT
        ),
        exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        max_concurrency=4,
        closeables=[client, llm],
    )

    async with pipeline:
        try:
            processed = await pipeline.run("all:galaxy", total_limit=50)
        except PipelineAborted as exc:
            print(f"Stopped early after {exc.partial_count} records: {exc}")
            return
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

## ما يفعله التشغيل {#what-a-run-does}

1. يجلب صفحة من القائمة (`page_size` سجلًا، 100 افتراضيًا) عند المؤشر الذي حفظه مدير
   الحالة (أو من الصفحة الأولى مع `start_index=0`)، ويتخطى السجلات المعالَجة مسبقًا.
   والصفحة التي لا تحوي إلا سجلات معالَجة يُتجاوز عنها، ولا تُعدّ نهاية للبيانات.
2. لكل سجل متبقٍّ، بحد أقصى `max_concurrency` سجلًا قيد المعالجة: مرشح الصلة ← جلب
   النص الكامل ← الاستيعاب الاختياري في الذاكرة ← استخراج الكيانات ← الكتابة إلى
   المصدِّر ← التعليم بأنه معالَج. ويُكتب السجل الذي لا كيانات له أيضًا، كي يستطيع
   المصدِّر مسح الصفوف التي لم تعد إعادة الاستخراج تجدها. وتُعلَّم السجلات غير ذات
   الصلة معالَجةً دون جلب نصها الكامل. أما السجلات التي يكون `record_id` فيها مفقودًا
   أو فارغًا فلا يمكن تتبّعها، فتُتخطى وتُسجَّل.
3. يفرّغ المصدِّر، فتصبح صفوف الصفحة دائمة؛ والمصدِّر الذي يخزّن مؤقتًا، مثل
   `AsyncCsvExporter`، لا تُعلَّم سجلاته معالَجةً إلا الآن. ثم يحفظ مؤشر القائمة
   ويكرر حتى تُعالَج `total_limit` من السجلات ذات الصلة أو تنتهي القائمة، منتظرًا
   `sleep_between` ثانية (0 افتراضيًا) قبل كل صفحة تالية. ولا يتقدم المؤشر إلا بعد
   الصفحات التي سُوّيت كل سجلاتها، والسجل الذي فشل في 3 تشغيلات يُتخطى بوصفه محجورًا؛
   راجع [الحالة والاستئناف والأخطاء](../guide/state.md).

لا تحتسب `total_limit` إلا السجلات **ذات الصلة**، ولا تُتجاوز أبدًا، وقيمتها
الافتراضية `page_size`. وكل وسائط `run()` بعد الاستعلام لا تُمرَّر إلا بأسمائها. ويجب
ألا تقل `max_concurrency` و`page_size` عن 1، وألا تكون `total_limit` سالبة؛ والقيم
الأخرى ترفع `ValueError` قبل إرسال أي طلب. كما ينتظر `AsyncArxivExtractor`
`sleep_before_search` ثانية (3 افتراضيًا) قبل كل طلب للقائمة، احترامًا لحدود المعدل
في arXiv.

عندما ينتهي التشغيل، أيًّا كانت طريقة انتهائه، يُفرَّغ المصدِّر ويُغلق: يكتب
`AsyncCsvExporter` الملف `results.csv` حينئذ، ويحتفظ بملف `results.csv.journal` أثناء
التشغيل. وعند الخروج ينتظر `async with pipeline` استدعاء `aclose()` على كل عنصر في
`closeables` له هذه الدالة: عميل HTTP، وعميل النموذج اللغوي، وأي
`AsyncSqliteStateManager` أو `AsyncSqliteEmbeddingStore` أو `AsyncSqliteFts5Store`
تستخدمه.

## يجب أن تطلب الموجِّهات JSON {#prompts-must-ask-for-json}

يطلب `AsyncOpenAICompatibleClient` وضع JSON
(`response_format={"type": "json_object"}`)، وترفض واجهة OpenAI البرمجية طلبات وضع
JSON التي لا تذكر رسائلها كلمة "JSON" أبدًا. أشكال الاستجابة التي تقرؤها المكتبة:

- يقرأ `AsyncLLMRelevanceFilter` المفتاح `relevant`. ويقبل قيمة منطقية، أو `0`/`1`،
  أو السلاسل `"true"` و`"false"` و`"yes"` و`"no"` و`"1"` و`"0"` بأي حالة أحرف. وكل ما
  عدا ذلك، بما فيه غياب المفتاح، يُعامل خطأً: يمر السجل، أو مع
  `default_on_error=False` يرفع المرشح `LLMError` ويُعاد السجل.
- يقرأ `AsyncLLMEntityExtractor` القائمة تحت `result_key` (افتراضيًا `"items"`)، أو
  القيمة الوحيدة إن كان للاستجابة مفتاح واحد بالضبط. ويجب أن تحوي القائمة كائنات؛
  و`null` تعني عدم وجود كيانات، والكائن المنفرد يُحتسب كيانًا واحدًا. وأي قيمة أخرى
  هناك ترفع `LLMError`، فيُعاد السجل. والاستجابة الفارغة، والاستجابة ذات المفاتيح
  المتعددة دون `result_key`، ترفعان `LLMError` كذلك، لذا سمِّ المفتاح في الموجِّه.
- يكتب `AsyncCsvExporter` المفاتيح المسمّاة في `columns` في أعمدتها الخاصة، وكل مفتاح
  آخر في العمود `extra` بصيغة JSON، فلا تضيع أي قيمة. مرّر نموذج Pydantic بوصفه
  `schema=` ليُتحقق من كل كيان؛ راجع [الكيانات المنمّطة](../guide/typed-entities.md).

## الخطوات التالية {#next-steps}

- شغّل خط المعالجة نفسه من شيفرة متزامنة باستخدام [`ETLPipeline`](blocking-usage.md).
- حمّل الإعدادات من YAML و`.env` باستخدام [الإعداد المنمّط](configuration.md).
- احتفظ بالورقة وجملة الدليل وراء كل قيمة باستخدام
  [الادعاءات ومصدرها](../guide/claims.md).
- نظّف ملف CSV وارسم بياناته باستخدام [خطوات المعالجة اللاحقة](../guide/post-processing.md).
