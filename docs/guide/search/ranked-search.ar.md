# البحث المرتَّب والتصفية

تأخذ المخازن استعلامات محلَّلة، أما `AsyncHybridSearcher` فيأخذ نصًا ويحلله مرة
واحدة قبل أي عملية إدخال وإخراج. يحتاج البحث المرتَّب إلى مصطلح يرتّب وفقه، ولذلك
فإن الاستعلام الذي تكون كل مصطلحاته منفية، مثل `NOT simulation` أو
`NOT simulation OR quasar`، يجعل `search` ترفع `SearchQueryError`. استخدم
`filter_ids` بدلًا من ذلك. فهي تقبل أي استعلام وتُعيد `frozenset` من معرّفات
السجلات، وهي مجموعة لا ترتيب لها فلا يمكن أن تُحسب ترتيبًا للنتائج:

```python
from sci_etl_core.search import parse_query

hits = await text_store.search(parse_query("photometr* dwarf"), limit=20)
observational = await text_store.filter_ids(parse_query("NOT simulation"))
```

لـ `TextHit` قيمة `score` تكون فيها القيمة الأعلى أفضل. ويعتمد مقياسها على
المجموعة النصية، فلا تقارن الدرجات إلا داخل قائمة نتائج واحدة.

## المقتطفات {#snippets}

`snippet` الخاص بالنتيجة نص عادي من الحقل الذي طابق على أفضل وجه، و`highlights`
تحمل إزاحات المحارف `[start, end)` للكلمات المطابقة داخله، لتطبّق الواجهة
ترميزها الخاص. ويُقتطع الحقل الأطول من 24 رمزًا إلى نافذة من 24 رمزًا حول
المطابقة، مع `…` في مواضع النص المحذوف.

وعندما يطابق الاستعلام في أكثر من حقل، تحمل `snippets` كائن `Snippet` لكل منها،
بالترتيب `title` ثم `abstract` ثم `body`، فتستطيع النتيجة أن تعرض المطابقة في
العنوان والمقطع من المتن معًا:

```python
from sci_etl_core.search import parse_query

for hit in await text_store.search(parse_query("dwarf OR photometr*"), limit=10):
    for snippet in hit.snippets:
        marked = [snippet.text[start:end] for start, end in snippet.highlights]
        print(f"{hit.record_id} {snippet.field}: {snippet.text} {marked}")
```

لا يظهر الحقل في `snippets` إلا عندما تُبرَز فيه كلمة مطابقة. ويُبرز مخزنا
النصوص الكلمات نفسها، إلا في الاستعلامات التي تحتسب فيها FTS5 أيضًا كلمة داخل
جزء من الاستعلام لا يطابق، وهو ما توثّقه `InMemoryTextSearchStore`.

تبني `passage_snippet(query, text)` بالطريقة نفسها `Snippet` لأي نص آخر، مُبرزةً
كل كلمة غير منفية في الاستعلام. ويستخدمها الباحث الهجين للمقاطع التي يجدها الفرع
الدلالي.

## ترتيب مجمع {#ranking-a-pool}

تأخذ `rank` الوسائط نفسها التي تأخذها `search`، وتُعيد النتائج نفسها بالترتيب نفسه
وبالدرجات نفسها، لكنها قد تترك مقتطفاتها وإبرازاتها وعنوانها وبياناتها الوصفية
فارغة. وتملؤها `hydrate` للنتائج التي تعرضها، فيُرتَّب المجمع الكبير دون حساب
مقتطف لكل نتيجة فيه:

```python
from sci_etl_core.search import parse_query

query = parse_query("dwarf galaxy")
pool = await text_store.rank(query, limit=500)
page = await text_store.hydrate(query, pool[:20])
```

- **الكلفة.** يرتّب `AsyncSqliteFts5Store` باستخدام `bm25()` وحدها، ولا يحسب
  المقتطفات ولا يقرأ العناوين والبيانات الوصفية إلا في `hydrate`، فلا يكلّف ترتيب
  500 نتيجة إلا أكثر قليلًا من ترتيب 20. وتعمل `search` الخاصة به بالطريقة نفسها
  داخل قراءة واحدة: ترتّب أولًا ولا تحسب المقتطفات إلا للنتائج التي تُعيدها.
  ويرتّب `AsyncHybridSearcher` مجمع المرشحين الخاص به بـ `rank` ولا يملأ بـ
  `hydrate` إلا النتائج التي يعرضها.
- **بين الاستدعاءين.** تقرأ `hydrate` الفهرس على حاله وقت استدعائها. والنتيجة
  التي حُذف سجلها بعد `rank`، أو لم يعد يطابق، تعود كما مُرِّرت، أما السجل الذي
  أُعيدت فهرسته في الأثناء فيحصل على مقتطفات نصه الجديد.
- **المخازن المخصصة** ترث `rank` تستدعي `search` و`hydrate` تُعيد النتائج دون
  تغيير، وهذا صحيح لأي مخزن؛ أعِد تعريف الاثنتين معًا للترتيب دون مقتطفات.
