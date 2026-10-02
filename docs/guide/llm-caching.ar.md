# التخزين المؤقت لاستجابات النموذج اللغوي

إعادة تشغيل خط المعالجة بعد انهيار، أو بعد تعديل موجِّه في مكان آخر، أو بعد تغيير
في شيفرة التصدير، تطرح على النموذج اللغوي الأسئلة نفسها من جديد. يجيب
`CachingLLMClient` عن الطلبات المتكررة من ذاكرة تخزين مؤقت، فلا تكلّف رموزًا وتعود
فورًا:

```python
from sci_etl_core import (
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    AsyncSqliteLLMResponseCache,
    CachingLLMClient,
)

cache = AsyncSqliteLLMResponseCache("cache/llm.db")
llm = CachingLLMClient(AsyncOpenAICompatibleClient.from_config(config.llm), cache)

relevance_filter = AsyncLLMRelevanceFilter(llm, relevance_prompt)
entity_extractor = AsyncLLMEntityExtractor(llm, extraction_prompt)
```

أدرج ذاكرة SQLite المؤقتة ضمن `closeables` في خط المعالجة ليُغلق اتصالها في نهاية
التشغيل.

## كيف تُطابَق الطلبات {#how-requests-are-matched}

يُبنى مفتاح الطلب من اسم النموذج، و`base_url` لنقطة النهاية، ودرجة الحرارة، وتنسيق
الاستجابة، ومخطط JSON Schema للطلب المنمّط، و`variant` الخاص بالعميل، والموجِّهَين
كليهما، ويُجزَّأ بخوارزمية SHA-256؛ ولا تدخل المهلة في المفتاح. فتغيير موجِّه النظام،
أو تغيير نص الورقة، أو اختلاف النموذج، أو المزوّد، أو درجة الحرارة، أو تنسيق
الاستجابة، أو تغيير مخطط الكيان، كلها تؤدي إلى إخفاق في الذاكرة المؤقتة. ويُسلسَل
المخطط بمفاتيح مرتبة، فالمخطط المساوي المكتوب بترتيب آخر يظل يصيب. والطلب الذي لا
مخطط له و`variant` فيه فارغ له المفتاح نفسه الذي كان له في 0.5.1.

يُبقي `CachingLLMClient(..., variant="sample-2")` إجاباته منفصلة عن إجابات عميل له
متغير آخر على الذاكرة المؤقتة نفسها، كأن تطرح سؤالًا مرتين عن قصد.

يقرأ `CachingLLMClient` القيم `base_url` و`temperature` و`response_format` من العميل
الذي يغلّفه. ويوفّر `AsyncOpenAICompatibleClient` الثلاث جميعها. ولكل عميل
`response_format`، وقيمته `{"type": "json_object"}` ما لم يُعِد صنف فرعي تعريفه؛ أما
العميل المخصص الذي يفتقر إلى `base_url` أو `temperature` فيُبنى مفتاحه دونهما.

## ما يُخزَّن مؤقتًا {#what-is-cached}

لا يُخزَّن الطلب الفاشل مؤقتًا أبدًا، فيُرسل من جديد في المرة التالية. ولا تُحفظ كذلك
الاستجابة التي ترفضها المكتبة:

- يرفض `AsyncLLMEntityExtractor` الاستجابة التي لا تحوي قائمة كيانات، أو التي لا
  تكون قائمة كياناتها قائمة كائنات.
- يرفض `AsyncLLMRelevanceFilter` الاستجابة التي لا تحمل حكمًا واضحًا.

كلاهما يستدعي `invalidate` على العميل، فيحذف `CachingLLMClient` الاستجابة المخزنة،
لتصل إعادة المحاولة في التشغيل التالي إلى النموذج بدلًا من إعادة الإجابة نفسها.

## الواجهات الخلفية {#backends}

- **`InMemoryLLMResponseCache(max_entries=None)`** يعيش ما دامت العملية قائمة. ومع
  `max_entries` تُطرد الاستجابة الأقدم استخدامًا عند امتلائه.
- **`AsyncSqliteLLMResponseCache(path)`** يحفظ الاستجابات في ملف SQLite بين
  التشغيلات. تُفرغه `clear()` وتُبلغ `count()` عن حجمه.

الواجهة الخلفية المخصصة، مثل Redis، ترث من `AsyncLLMResponseCache` وتنفّذ `get`
و`set` و`delete` و`clear`. والواجهة الخلفية التي تفتقر إلى `delete` تظل تعمل، لكن كل
استجابة مرفوضة تبقى مخزنة وتُسجَّل بوصفها عطلًا في الذاكرة المؤقتة.

## عندما تتعطل الذاكرة المؤقتة {#when-the-cache-fails}

لا تُفشل الذاكرة المؤقتة أي طلب إلى النموذج أبدًا. فإن رفعت القراءة منها أو الكتابة
فيها استثناءً، سُجّل الخطأ بوصفه `LLM cache get failed: ...` أو
`LLM cache set failed: ...` أو `LLM cache delete failed: ...`، بالمستوى `WARNING` على
المسجِّل `sci_etl_core.llm.cache_async`، وذهب الطلب إلى النموذج اللغوي كأن لا شيء
مخزَّن. تعدّ `stats` القيم `hits` و`misses` و`faults`، و`usage` هو استهلاك العميل
المغلَّف، فلا تكلّف الإصابات في الذاكرة المؤقتة أي رموز:

```python
print(llm.stats, llm.usage)
```
