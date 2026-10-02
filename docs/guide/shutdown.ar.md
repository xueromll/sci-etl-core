# الإيقاف السلس

مرّر `ShutdownSignal` إلى خط المعالجة، فيوقف SIGINT (Ctrl+C) أو SIGTERM التشغيل
بنظافة:

```python
from sci_etl_core import AsyncETLPipeline, PipelineInterrupted
from sci_etl_core.signals import ShutdownSignal

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
    shutdown=ShutdownSignal(),
)

try:
    count = await pipeline.run(query="all:galaxy", total_limit=500)
except PipelineInterrupted as stopped:
    print(f"Stopped after {stopped.partial_count} records; the next run picks up the rest")
```

يثبّت خط المعالجة معالجات الإشارات طوال مدة كل `run()` ثم يعيد المعالجات السابقة
بعد ذلك.

- **الإشارة الأولى:** لا يبدأ أي سجل جديد. تكتمل السجلات الجارية، ويُفرَّغ
  المصدِّر، وتُعلَّم السجلات التي جعلها هذا التفريغ دائمة على أنها معالَجة؛ أما
  السجلات التي لم تبدأ فتبقى دون تعليم للتشغيل التالي. ويُلغى فورًا أي طلب قائمة
  معلّق أو انتظار بين الصفحات. ولا يتقدم المؤشر المحفوظ إلى ما بعد الصفحة التي
  قُطعت. ثم يُغلق المصدِّر، وتُحفظ الحالة، وترفع `run()` الاستثناء
  `PipelineInterrupted` حاملًا عدد السجلات المعالَجة.
- **الإشارة الثانية:** تعيد المعالج السابق وتُنهي العملية فورًا.
- **الإيقاف البرمجي:** توقف `shutdown.request()` التشغيل بالطريقة نفسها، من
  معالج ويب أو اختبار مثلًا.

`PipelineInterrupted` صنف فرعي من `PipelineAborted`، فيظل أي
`except PipelineAborted` موجود يلتقطه. التقط `PipelineInterrupted` أولًا عندما
ينبغي أن يخرج التشغيل المقاطَع بطريقة مختلفة عن التشغيل الفاشل.

## خط المعالجة المتزامن {#the-synchronous-pipeline}

يقبل `ETLPipeline` الوسيط `shutdown` نفسه. ويجري عمله على حلقة أحداث خلفية،
ولذلك تُثبَّت المعالجات على الخيط الذي يستدعي `run()` وتمرر الطلب إلى تلك الحلقة.
استدعِ `run()` من الخيط الرئيسي، لأن الخيط الرئيسي وحده يتلقى الإشارات:

```python
from sci_etl_core import ETLPipeline
from sci_etl_core.signals import ShutdownSignal

with ETLPipeline(..., shutdown=ShutdownSignal()) as pipeline:
    pipeline.run(query="all:galaxy", total_limit=500)
```

## تفريغ المصدِّر والحالة {#flushing-the-exporter-and-state}

ينتهي كل تشغيل بتفريغ المصدِّر وإغلاقه، ثم باستدعاء `flush()` لمدير الحالة، أيًّا
كانت طريقة انتهائه: مكتملًا أو مُجهَضًا أو مقاطَعًا أو ملغى. يكتب
`AsyncCsvExporter` ملف CSV عند إغلاقه، ويُنشئ `AsyncSqliteStateManager` نقطة
تثبيت لسجل الكتابة المسبقة في `flush()`. وعندما يكون التشغيل نفسه قد فشل، يُسجَّل
فشل التفريغ أو الإغلاق بدلًا من رفعه، كي لا يُخفي الخطأ الأصلي.

## معالجاتك الخاصة {#handlers-of-your-own}

تثبّت `shutdown.guard()` المعالجات لكتلة من شيفرتك الخاصة. ويمكن تداخل هذه
الحمايات، فخط المعالجة الذي يُعطى الإشارة نفسها داخل تلك الكتلة يترك معالجاتك في
مكانها عند انتهاء تشغيله. ولا تُثبَّت المعالجات إلا من الخيط الرئيسي؛ وفي غيره
تسجّل `guard()` رسالة ولا تثبّت شيئًا، بينما تظل `request()` تعمل.
