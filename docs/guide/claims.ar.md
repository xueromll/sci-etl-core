# الادعاءات ومصدرها

الادعاء قيمة واحدة أو عبارة واحدة مستخرجة من ورقة، تُخزَّن مع الورقة التي جاءت منها،
والجملة التي قُرئت منها، والنموذج والموجِّه والمخطط التي أنتجتها. وتتيح الادعاءات للجدول
أن يجيب عن سؤال "أي ورقة تقول ذلك؟" لكل قيمة، وأن يحتفظ بالتقارير المتعارضة جنبًا إلى
جنب، وأن يجد كل قيمة يجب إعادة استخراجها بعد إصلاح موجِّه.

!!! note "مؤقتة"
    `sci_etl_core.claims` جديدة في 0.6.0 ومؤقتة: قد يتغير أي اسم فيها في إصدار فرعي،
    مع إدخال في CHANGELOG، إلى أن يعتمد عليه مستهلك معروف.

## استخراج الادعاءات {#extracting-claims}

يطلب `AsyncLLMClaimExtractor` من النموذج كائنات `ClaimDraft`، ويتحقق منها، ويحدد موضع
اقتباس كل مسودة في النص المرسل إلى النموذج، ويُعيد كائنات `Claim`. ويخزّنها
`AsyncClaimStoreExporter` سجلًا تلو سجل:

```python
import os

from sci_etl_core import AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.claims import (
    AsyncClaimStoreExporter,
    AsyncLLMClaimExtractor,
    AsyncSqliteClaimStore,
    AsyncSqliteRejectionStore,
)

CLAIM_PROMPT = (
    "List every measurement of an ultra-diffuse galaxy in the paper. Reply with JSON: "
    '{"claims": [{"kind": "measurement", "subject": "...", "predicate": "effective_radius", '
    '"quantity": {"verbatim": "2.9 kpc", "value": 2.9, "unit_text": "kpc"}, '
    '"context": {"band": "g"}, "quote": "the sentence, copied exactly"}]}.'
)

llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"], base_url="https://api.openai.com/v1", model="gpt-4o-mini"
)
claims = AsyncSqliteClaimStore("data/claims.db")
rejections = AsyncSqliteRejectionStore("data/rejections.db")

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=AsyncLLMClaimExtractor(llm, CLAIM_PROMPT, rejections=rejections),
    exporter=AsyncClaimStoreExporter(claims),
    state_manager=state_manager,
    closeables=[llm, claims, rejections],
)
```

ارث من `ClaimDraft` لتضييق `predicate` أو مفاتيح `context` بما يناسب مجالك، ومرّر
الصنف الفرعي بوصفه `schema=`. ولا يقدّم النموذج أبدًا المعرّفات ولا الإزاحات ولا بيانات
المصدر؛ فالشيفرة هي التي تحسبها.

## ما يحويه الادعاء {#what-a-claim-holds}

| الحقل | المعنى |
|-------|--------|
| `claim_id` | خلاصة (digest) للسجل والنوع والموضوع والمحمول والمفعول والقطبية والسياق والنص الحرفي للكمية والمقطع وتجزئة المخطط |
| `kind` | `"measurement"`، الذي يحتاج إلى `quantity`، أو `"assertion"`، الذي يحتاج إلى `object` |
| `subject`، `predicate`، `object` | ما يدور حوله الادعاء، كما تسمّيه الورقة |
| `quantity` | العدد كما تكتبه الورقة: `verbatim`، `value`، `unit_text`، `qualifier`، `uncertainty` |
| `statistics` | أحجام الأثر، وحدود الثقة، و*p*، وإحصاءات الاختبار، وأحجام المجموعات، وكلها اختيارية |
| `context` | شروط مثل النطاق الطيفي أو العينة، في صورة أزواج مفتاح–قيمة مرتبة |
| `span` | `record_id`، وإزاحتا بداية ونهاية الجملة أو الجمل التي وُجد فيها الاقتباس، والاقتباس نفسه |
| `stamp` | النموذج، وتجزئة الموجِّه، وتجزئة المخطط، وإصدار المكتبة |

يُستبعد النموذج والموجِّه وإصدار المكتبة من `claim_id` عن قصد: فإعادة استخراج ورقة
بنموذج آخر تعطي المعرّفات نفسها حيثما تطابقت الحقول، مع ختم جديد. وتُقارن المواضيع
مقارنة حرفية، فيكون `"DF44"` و`"DF 44"` ادعاءين مختلفين؛ أما توحيد الأسماء فخطوة لاحقة
لا تعيد كتابة الادعاءات أبدًا. وتعطي `Claim.to_row()` ربطًا مسطحًا واحدًا، وهو الشكل
الذي تكتبه المخازن ومصدِّرا CSV وJSON Lines.

## الإسناد إلى النص {#grounding}

تجد `locate_quote(text, quote)` الاقتباس في النص المرسل إلى النموذج، مطابقةً حرفيًا بعد
ضغط المسافات، وإلا فمطابقةً تقريبية بـ `difflib` بنسبة `min_ratio` (0.9) أو أعلى، ثم
توسّع المطابقة إلى جمل كاملة. ويعرف مقسِّم الجمل أسلوب النثر العلمي: فلا تُنهي `et al.`
و`Fig. 3` و`Eq. (2)` و`i.e.` و`R.A.` والأعداد العشرية الجملة. والمسودة التي لا يوجد
اقتباسها تُعدّ غير مسنَدة: تُسجَّل، وتوضع في مخزن الرفض بالرمز `"ungrounded"`، ولا
تُعاد.

## المخازن {#stores}

يتشارك `InMemoryClaimStore` و`AsyncSqliteClaimStore` عقدًا واحدًا:

- تستبدل `replace_record(record_id, claims)` ادعاءات السجل في معاملة واحدة وتُعيد
  المراجعة الجديدة. والقائمة الفارغة تمسح السجل، وهو ما يحدث حين لا تجد إعادة
  الاستخراج شيئًا، لأن خط المعالجة يكتب كل سجل معالَج.
- تقرأ `claims_for_records(record_ids)` الادعاءات من جديد، بالترتيب المخزَّن.
- تتنقل `changes_since(revision)` صفحةً صفحة بين ما تغيّر، حسب رقم المراجعة الذي لا
  يزداد إلا نموًا، فتستطيع مهمة لاحقة أن تستأنف من حيث توقفت.

يفهرس مخزن SQLite الادعاءات حسب السجل، وحسب `(subject, predicate, object)`، وحسب زوج
السياق، وحسب النوع والقيمة المعياريين، ويسجّل إصدار مخططه، فتفتح نسخة لاحقة من
sci-etl-core الملفات التي كتبها 0.6.0.

عطل المخزن في `AsyncClaimStoreExporter.write` يُفشل السجل، فيُعاد في التشغيل التالي
ويُحتسب محاولة واحدة، مثل أي سجل فاشل. وليس هذا عطلًا في الذاكرة.
