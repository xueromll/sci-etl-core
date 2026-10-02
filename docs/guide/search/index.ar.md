# البحث والاستكشاف المحليان

يضيف فهرس نصي بجوار الذاكرة المتجهية البحثَ البولياني، والبحثَ الهجين الذي يدمج
الترتيب بالكلمات المفتاحية والترتيب بالمعنى، وأوجهَ البيانات الوصفية، ورسومًا
بيانية للأوراق المترابطة. ويقع كل ذلك في `sci_etl_core.search` ولا يحتاج إلا إلى
`sqlite3` من المكتبة القياسية، فيعمل مع `pip install sci-etl-core` المجرد. لا
تثبّت الإضافة `search` شيئًا؛ وإنما تتيح لملف المتطلبات أن يذكر سبب وجود الحزمة.
ولا يحتاج إلى الإضافة `embeddings` إلا الجانب الدلالي.

## الفهرسة من خط المعالجة {#indexing-from-the-pipeline}

يوسّع هذا المثال مثال [الذاكرة الدلالية](../semantic-memory.md)، بحيث يُفهرَس كل
سجل ذي صلة لنوعَي البحث كليهما:

```python
import os

from sci_etl_core import AsyncCompositeIngestor
from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)
from sci_etl_core.search import AsyncHybridSearcher, AsyncSearchIndexer, AsyncSqliteFts5Store

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
vector_store = AsyncSqliteEmbeddingStore("memory.db")
text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))

ingestor = AsyncCompositeIngestor(
    AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=vector_store),
    AsyncSearchIndexer(store=text_store),
)


async def show_matches(query: str) -> None:
    searcher = AsyncHybridSearcher(text_store, AsyncSimilarArticleFinder(embedder, vector_store))
    outcome = await searcher.search(query, top_k=10)
    if outcome.degraded:
        print(f"Degraded: {', '.join(outcome.degraded)}")
    for hit in outcome.hits:
        print(f"{hit.score:.4f}  {hit.record_id}  {hit.title}")
```

أضف المستوعِب إلى خط المعالجة من [البدء السريع](../../getting-started/quick-start.md):

```python
pipeline = AsyncETLPipeline(
    ...,
    memory_ingestor=ingestor,
    closeables=[client, llm, embedder, vector_store, text_store],
)
```

- **إغلاق المخازن.** يوضع `text_store` في `closeables` للسبب نفسه الذي يوضع من
  أجله `vector_store`، لأن هذا سكربت يُشغَّل مرة واحدة: خط المعالجة يملك المخزنين،
  لذا يجب أن تعمل `show_matches` داخل `async with pipeline`. أما التطبيق طويل
  العمر فيتبع [ملكية المخازن](store-ownership.md) بدلًا من ذلك.
- **أعطال الذاكرة.** يُسجَّل `SearchStoreError` أثناء الفهرسة بوصفه تحذيرًا،
  `Memory ingest failed for <record_id> in AsyncSearchIndexer: ...`، على المسجِّل
  `sci_etl_core.ingest_async`، وتظل مقاطع السجل تُضمَّن وكياناته تُصدَّر. وبالمثل
  لا يؤثر عطل التضمين في الفهرس النصي. أما `SearchQueryError` فليس عطلًا في
  الذاكرة، ويُفشل السجل.
- **ترتيب المستوعِبات.** يُعيد `AsyncCompositeIngestor` عدَّ مستوعِبه الأول، لذا
  مرّر مستوعِب المقاطع أولًا؛ ووضع `AsyncSearchIndexer` في المقدمة يرفع
  `ValueError`. ودون تضمينات، مرّر `AsyncSearchIndexer` مباشرة إلى
  `memory_ingestor=`.
- **ما يُفهرَس.** مستند واحد لكل سجل، يحوي عنوانه وملخصه ونصه الكامل و`metadata`.
  وإعادة استيعاب السجل تستبدل مستنده، والسجل الذي يكون عنوانه وملخصه ونصه كلها
  فارغة يُحذف.

## في هذا القسم {#in-this-section}

- [صياغة الاستعلامات](query-syntax.md): لغة الاستعلام البوليانية ومحلّلها.
- [البحث المرتَّب والتصفية](ranked-search.md): `search` مقابل `filter_ids`، والمقتطفات.
- [البحث الهجين](hybrid-search.md): دمج BM25 مع تشابه التضمينات.
- [المرشحات والأوجه](filters-and-facets.md): مرشحات البيانات الوصفية والنطاقات، وأعداد الأوجه والنطاقات.
- [مخازن النصوص](text-stores.md): الفهرس في الذاكرة وفهرس SQLite FTS5.
- [الملء من الذاكرة المتجهية](backfill.md): بناء الفهرس النصي من المقاطع المخزنة.
- [رسوم الاستكشاف البيانية](discovery-graphs.md): رسوم بيانية للأوراق المترابطة.
- [بناء واجهة مستخدم](user-interfaces.md): نموذج القراءة الذي تعرضه الواجهة.
- [ملكية المخازن](store-ownership.md): مَن يُغلق المخزن، ومتى.
