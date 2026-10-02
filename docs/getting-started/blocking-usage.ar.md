# الاستخدام المتزامن

`ETLPipeline` هو الصنف المتزامن الوحيد. يقبل الوسائط نفسها التي يقبلها
`AsyncETLPipeline`، بما فيها المكوّنات **غير المتزامنة** نفسها، إضافة إلى
`run_timeout`:

```python
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    ETLPipeline,
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

client = build_async_client()
llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
)

with ETLPipeline(
    extractor=AsyncArxivExtractor(
        client=client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
    ),
    relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
    entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
    exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
    closeables=[client, llm],
    run_timeout=3600,
) as pipeline:
    try:
        processed = pipeline.run(query="all:galaxy", total_limit=50)
    except PipelineAborted as exc:
        processed = exc.partial_count

print(f"Processed {processed} relevant records")
```

- **لا توجد نسخ متزامنة للمكوّنات المفردة.** لاستدعاء مستخرِج أو عميل أو مصدِّر
  مباشرة من شيفرة متزامنة، ضع الاستدعاءات داخل دالة غير متزامنة (coroutine)
  وشغّلها بـ `asyncio.run`. ولتوصيل شيفرة متزامنة بخط معالجة، نفّذ الواجهة غير
  المتزامنة وشغّل العمل المتزامن داخلها بـ `asyncio.to_thread`، كما تُستدعى
  المحلِّلات والمعالِجات المضمّنة.
- **`run_timeout`** بالثواني، وغير محدود افتراضيًا. عند انقضائه يُلغى التشغيل
  ويُرفع `TimeoutError`.
- **حلقة الأحداث.** يشغّل `ETLPipeline` خط المعالجة على خيط خلفي مشترك لحلقة
  أحداث. يعمل من السكربتات العادية، وكذلك عند استدعائه من داخل حلقة أحداث قيد
  التشغيل (مثل دفتر Notebook). ومع ذلك فهو يحجب الخيط المستدعي حتى ينتهي التشغيل،
  لذا استخدم `await` مع `AsyncETLPipeline` في الشيفرة غير المتزامنة. وبمجرد أن
  يستخدم `ETLPipeline` مكوّنًا ما، يصبح ذلك المكوّن ملكًا للحلقة الخلفية، فلا
  تستخدمه أيضًا من حلقة أحداثك الخاصة.
- **`with ETLPipeline(...)`** يُغلق `closeables` عند الخروج، ويمنح كل مورد ما
  يصل إلى 30 ثانية.
