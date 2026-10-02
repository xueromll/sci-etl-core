# أحداث التقدم والمقاييس

يجمع كل تشغيل لخط المعالجة مقاييس، ويمكنه الإبلاغ عن تقدمه أثناء سيره.

## مقاييس التشغيل {#run-metrics}

تُعيد `pipeline.last_run_metrics` كائن `RunMetrics` لأحدث تشغيل، أيًّا كانت طريقة
انتهائه:

```python
from sci_etl_core import AsyncETLPipeline

pipeline = AsyncETLPipeline(..., usage_sources=[llm, embedder])
try:
    await pipeline.run(query="all:galaxy", total_limit=200, newest_first=True)
finally:
    metrics = pipeline.last_run_metrics
    print(
        f"{metrics.outcome}: {metrics.processed} processed, {metrics.irrelevant} irrelevant, "
        f"{metrics.failed} failed in {metrics.duration_seconds:.0f} s"
    )
```

| الحقل | المعنى |
|-------|--------|
| `pages`، `listed` | صفحات القائمة المجلوبة والمدخلات التي احتوتها |
| `processed`، `irrelevant`، `deferred`، `failed`، `skipped` | السجلات حسب النتيجة؛ تنتظر سجلات `deferred` التشغيل التالي بسبب `total_limit` أو إيقاف، وسجلات `skipped` لم يكن لها معرّف |
| `entities_exported` | الكيانات المسلَّمة إلى المصدِّر |
| `memory_faults` | أعطال الاستيعاب في الذاكرة التي سُجّلت دون أن تُفشل سجلها |
| `quarantined` | السجلات المدرجة التي تُخطّيت لأنها فشلت `max_attempts` مرة في تشغيلات سابقة، ويُحسب كل منها مرة واحدة في كل تشغيل |
| `listing_truncated` | `True` عندما أوقف المصدر القائمة عند حد نتائجه |
| `duration_seconds` | الزمن الفعلي للتشغيل |
| `token_usage` | الرموز التي استهلكتها `usage_sources` أثناء هذا التشغيل، أو `None` دون مصادر |
| `outcome` | `completed` أو `aborted` أو `interrupted` أو `cancelled` أو `failed` |

تقبل `usage_sources` أي كائنات لها الخاصية `usage`، مثل
`AsyncOpenAICompatibleClient` أو `AsyncOpenAIEmbedder` أو `CachingLLMClient`.
ويُطرح استهلاكها السابق للتشغيل، فيُبلغ العميل المشترك بين عدة تشغيلات عن كل تشغيل
على حدة.

## أحداث التقدم {#progress-events}

مرّر `on_event` لتلقي أحداث منمّطة من `sci_etl_core.observability` مع تقدم التشغيل:

```python
from sci_etl_core.observability import PageFinished, RecordFinished, RunFinished


def report(event):
    if isinstance(event, RecordFinished) and event.outcome == "failed":
        print(f"{event.record_id} failed after {event.duration_seconds:.1f} s: {event.error!r}")
    elif isinstance(event, PageFinished):
        print(f"page at {event.cursor or 'start'}: {event.metrics.processed} processed so far")
    elif isinstance(event, RunFinished):
        print(f"run {event.metrics.outcome}")


pipeline = AsyncETLPipeline(..., on_event=report)
```

| الحدث | متى |
|-------|-----|
| `RunStarted(query, start_index, total_limit, newest_first, cursor)` | قبل أول طلب للقائمة |
| `PageFetched(offset, entries, new_records, cursor, truncated)` | وصلت صفحة من القائمة؛ لم تُعالَج `new_records` بعد، وتشير `truncated` إلى الصفحة التي توقف عندها المصدر عند حد نتائجه |
| `RecordFinished(record_id, title, outcome, duration_seconds, entities, error)` | غادر سجل خط المعالجة في هذا التشغيل |
| `PageFinished(offset, duration_seconds, metrics, cursor)` | انتهت كل سجلات الصفحة؛ و`metrics` هي التشغيل حتى الآن |
| `RunFinished(metrics)` | انتهى التشغيل، أيًّا كانت طريقة انتهائه |

`cursor` هو مؤشر القائمة الذي طُلبت به الصفحة، و`None` للصفحة الأولى. وتحمل
`start_index` و`offset` الموضع نفسه بوصفه إزاحة في القائمة عندما يتنقل المستخرِج بين
الصفحات بالإزاحة، وتكونان `None` في غير ذلك. وكل حدث وكذلك `RunMetrics` صنف بيانات
(dataclass) لا يقبل إلا الوسائط المسمّاة.

يعمل المعالج على حلقة الأحداث، فاجعله سريعًا: سلّم العمل البطيء، كاستدعاء شبكي، إلى
طابور. وأي استثناء يرفعه يُسجَّل بوصفه `Event handler failed: ...` ولا يوقف التشغيل
أبدًا. ويقبل `ETLPipeline` الوسائط نفسها ويوفّر `last_run_metrics` كذلك.
