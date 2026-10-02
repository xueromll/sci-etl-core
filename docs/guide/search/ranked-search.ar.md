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
