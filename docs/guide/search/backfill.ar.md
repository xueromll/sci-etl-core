# الملء من الذاكرة المتجهية

النشر الذي عمل بذاكرة دلالية دون فهرس نصي يحتفظ أصلًا بالنص الكامل لكل سجل ذي صلة،
مقسّمًا إلى مقاطع، في `AsyncSqliteEmbeddingStore` الخاص به. وتبني
`backfill_text_index` الفهرس النصي من تلك المقاطع، فلا حاجة إلى جلب أي شيء أو
تضمينه من جديد:

```python
import asyncio

from sci_etl_core.embeddings import AsyncSqliteEmbeddingStore, SlidingWindowChunker
from sci_etl_core.search import AsyncSqliteFts5Store, backfill_text_index


async def backfill() -> None:
    vector_store = AsyncSqliteEmbeddingStore("memory.db")
    text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))
    try:
        report = await backfill_text_index(
            vector_store,
            text_store,
            overlap_words=SlidingWindowChunker().overlap_words,
        )
        print(f"{report.indexed} indexed, {report.skipped_existing} already there, {report.skipped_empty} empty")
    finally:
        await vector_store.aclose()
        await text_store.aclose()


asyncio.run(backfill())
```

شغّلها مرة واحدة، حين لا يكتب أي خط معالجة في أيٍّ من المخزنين، ثم أضف
`AsyncSearchIndexer` إلى خط المعالجة كما يوضح [البحث والاستكشاف المحليان](index.md)،
لتُفهرَس السجلات الجديدة فور وصولها.

## المقاطع المتداخلة {#overlapping-chunks}

يجعل `SlidingWindowChunker` المقاطع المتجاورة متداخلة، بمقدار 50 كلمة افتراضيًا،
كي لا يُقطع أي مقطع عند حد نافذة. وضمّ المقاطع كما هي سيكرر تلك الكلمات، فيحتسب
BM25 كل كلمة عند الحد مرتين. ويُزيل الملء التداخل بـ `merge_passages`، التي تحذف أول
`overlap_words` كلمة من كل مقطع عندما تكرر نهاية المقطع السابق، فيعود المتن وكل
كلمة فيه مرة واحدة.

مرّر `overlap_words` الخاصة بالمقطِّع الذي كتب المقاطع. فمع
`SlidingWindowChunker(chunk_words, overlap_words)` مرّر `overlap_words` نفسها؛ وإن
كنت قد أغفلتها، فاقرأها من مقطِّع بُني بالطريقة نفسها، كما يفعل المثال. والمقطع
الذي لا تكرر كلماته الأولى الكلمات الأخيرة من المقطع السابق يُحفظ كاملًا، فالقيمة
الخاطئة تترك الكلمات المكررة في المتن بدلًا من قص نص منه.

يعود المتن بمسافة واحدة بين الكلمات، كما قسّمه المقطِّع؛ وتختفي فواصل الأسطر
والمسافات بين الفقرات، وهو ما لا يغيّر المطابقات.

## ما يحويه المستند المملوء {#what-a-backfilled-document-holds}

تحتفظ الذاكرة المتجهية بأقل مما كان لدى خط المعالجة، ولذلك يحوي المستند المملوء
افتراضيًا:

| الحقل | القيمة |
|-------|--------|
| `title` | قيمة `title` المخزنة مع مقاطع السجل |
| `abstract` | فارغ، لأن المقاطع لا تحويه |
| `body` | المقاطع مدموجة |
| `metadata` | بقية البيانات الوصفية للمقاطع، مثل `source_url` |

لا يخزّن `AsyncChunkIngestor` قيمة `RawRecord.metadata` مع المقاطع، فلا يكون للمستند
المملوء `categories` ولا `year` ولا غيرها من وسوم الأوجه، ولا تطابقه المرشحات على تلك
المفاتيح. وإن كانت تلك البيانات الوصفية متاحة لديك في مكان آخر، كملف CSV المصدَّر،
فمرّر `build_document` تضيفها. تتلقى `StoredRecord` والمتن المدموج، وتُعيد
`SearchDocument` المراد فهرسته، أو `None` لاستبعاد السجل:

```python
from sci_etl_core.search import SearchDocument, backfill_text_index, stored_record_document


def with_catalogue_metadata(record, body):
    document = stored_record_document(record, body)
    if document is None or record.record_id not in catalogue:
        return document
    entry = catalogue[record.record_id]
    document.abstract = entry["abstract"]
    document.metadata.update(categories=entry["categories"], year=entry["year"])
    return document


report = await backfill_text_index(
    vector_store, text_store, overlap_words=50, build_document=with_catalogue_metadata
)
```

## السجلات الموجودة في الفهرس أصلًا {#records-already-in-the-index}

للسجل الذي فهرسه خط المعالجة من قبل ملخصه وبياناته الوصفية، وهي ما يفتقر إليه
المستند المملوء، ولذلك يتركه الملء على حاله ويحتسبه في `skipped_existing`. مرّر
`replace_existing=True` للكتابة فوق كل سجل من الذاكرة المتجهية، كأن يكون ذلك بعد إعادة
بناء فهرس نصي من الصفر. أما سجلات الفهرس النصي غير الموجودة في الذاكرة المتجهية فلا
تُمسّ أبدًا.

- **الدفعات.** تُقرأ السجلات وتُكتب `batch_size` سجلًا في كل مرة (100 افتراضيًا)، دون
  تحميل أي متجه، فيبقى استهلاك الذاكرة ثابتًا مع المخزن الكبير.
- **المخازن المتجهية الأخرى.** يستطيع `InMemoryEmbeddingStore`
  و`AsyncSqliteEmbeddingStore` سرد سجلاتهما عبر `iter_records`. أما
  `AsyncEmbeddingStore` المخصص الذي لا ينفّذها فيرفع `NotImplementedError`.
- **الملكية.** لا تُغلق `backfill_text_index` أيًّا من المخزنين؛ أغلقهما بنفسك، كما
  يفعل المثال.
