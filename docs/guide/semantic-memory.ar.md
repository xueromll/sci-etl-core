# الذاكرة الدلالية

الذاكرة الدلالية اختيارية وتحتاج إلى الإضافة `embeddings`. مرّر
`memory_ingestor` لتقطيع النص الكامل لكل سجل ذي صلة وتضمينه في مخزن متجهي. ويمكنك
بعدئذ البحث في ذلك المخزن بالمعنى:

```python
import os

from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
store = AsyncSqliteEmbeddingStore("memory.db")
ingestor = AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=store)


async def show_similar(text: str) -> None:
    finder = AsyncSimilarArticleFinder(embedder, store)
    for record_id, score, metadata in await finder.find_similar_articles(text, top_k=5):
        print(f"{score:.2f}  {record_id}  {metadata['title']}")
```

أضف المستوعِب إلى خط المعالجة من [البدء السريع](../getting-started/quick-start.md)،
وأدرج مولّد التضمينات والمخزن ضمن `closeables` الخاصة به:

```python
pipeline = AsyncETLPipeline(..., memory_ingestor=ingestor, closeables=[client, embedder, store])
```

- **ما يُخزَّن.** يجري الاستيعاب بعد بوابة الصلة، فلا تُضمَّن إلا السجلات ذات
  الصلة. يستخدم `SlidingWindowChunker` افتراضيًا نوافذ من 350 كلمة بتداخل 50
  كلمة. وإعادة استيعاب السجل تستبدل كل مقاطعه، فالنص الذي صار ينتج مقاطع أقل لا
  يخلّف وراءه شيئًا قديمًا.
- **الأعطال.** يُسجَّل `EmbeddingError` أو `EmbeddingStoreError` أثناء الاستيعاب،
  وتظل كيانات السجل تُصدَّر. ويشمل ذلك ملف ذاكرة ليس قاعدة بيانات SQLite، ومولّد
  تضمينات يُعيد عددًا من المتجهات يختلف عن عدد المقاطع.
- **المخازن.** `InMemoryEmbeddingStore()` مناسب للاختبارات وعمليات التشغيل
  القصيرة. أما `AsyncSqliteEmbeddingStore` فيحفظ المتجهات بالوحدة `sqlite3` من
  المكتبة القياسية ويحسب درجة كل متجه مخزَّن في كل استعلام. ويُبقي المتجهات في
  الذاكرة بين الاستعلامات ولا يعيد قراءتها إلا بعد عملية كتابة، من هذا المخزن أو
  من عملية أخرى، فيزداد استهلاك الذاكرة مع حجم المخزن. ويُسلسِل الوصول إلى اتصاله،
  فيمكن للسجلات المتزامنة أن تتشارك مخزنًا واحدًا، وكل عملية كتابة معاملة واحدة.
  ولا يظهر في النتائج أبدًا أي متجه مخزَّن يحوي NaN أو ما لا نهاية.
- **المخازن المخصصة.** تنفّذ الأصناف الفرعية من `AsyncEmbeddingStore` الدوال
  `add` و`delete_record` و`query` و`count`. وتقوم `replace_record` افتراضيًا
  بالحذف ثم الإضافة؛ أعِد تعريفها إن كانت واجهتك الخلفية قادرة على تنفيذ الأمرين
  ذرّيًا.
- **قراءة الذاكرة.** ترتّب `finder.find_best_chunks(text, top_k=5)` المقالات كما
  تفعل `find_similar_articles`، لكنها تُعيد أفضل `SearchHit` لكل مقالة، مع نص
  المقطع، لعرض المقطع الذي طابق. وتُخرج `iter_records()` الخاصة بالمخزن مقاطع كل
  سجل في صورة `StoredRecord`، دون تحميل المتجهات.
- **التضمينات المحلية.** يولّد `AsyncSentenceTransformerEmbedder("all-MiniLM-L6-v2")`
  التضمينات دون اتصالات شبكية. ويحتاج إلى الإضافة `embeddings-local`، ويحمّل
  النموذج عند إنشائه، ويقبل نموذجًا محمّلًا مسبقًا عبر `model=`.

## الصلة دون نموذج لغوي {#relevance-without-an-llm}

يُبقي `AsyncEmbeddingRelevanceFilter` السجل عندما يكون عنوانه وملخصه قريبين
بدرجة كافية من أي نص مرجعي:

```python
from sci_etl_core import AsyncEmbeddingRelevanceFilter

relevance_filter = AsyncEmbeddingRelevanceFilter(
    embedder=embedder,
    reference_texts=["ultra-diffuse galaxies", "low surface brightness galaxies"],
    threshold=0.35,  # الحد الأدنى لتشابه جيب التمام
)
```

## البحث بالكلمات المفتاحية أيضًا {#searching-by-keyword-too}

لفهرسة السجلات نفسها للبحث البولياني أيضًا، راجع
[البحث والاستكشاف المحليان](search/index.md). وفهرسه النصي في SQLite،
`AsyncSqliteFts5Store`، مخزن إضافي يُدرج في `closeables` بجوار مخزن التضمينات، ولا
تثبّت إضافته `search` شيئًا. ويمكن فهرسة ذاكرة مُلئت قبل إضافة الفهرس النصي من
مقاطعها المخزنة؛ راجع [الملء من الذاكرة المتجهية](search/backfill.md).
