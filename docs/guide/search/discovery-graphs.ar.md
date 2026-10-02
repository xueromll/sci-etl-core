# رسوم الاستكشاف البيانية

تُنمّي `build_discovery_graph` رسمًا بيانيًا للأوراق المترابطة حول سجل بذرة، على
نهج Connected Papers، انطلاقًا من مصادر حواف تربط السجلات وفق التشابه:

```python
from sci_etl_core.search import (
    EmbeddingEdgeSource,
    GraphParams,
    MetadataEdgeSource,
    MetadataFilter,
    build_discovery_graph,
    filter_graph,
)


async def show_neighborhood(record_id: str) -> None:
    sources = [
        EmbeddingEdgeSource(embedder, vector_store, text_store),
        MetadataEdgeSource(text_store, keys=("categories",)),
    ]
    graph = await build_discovery_graph(record_id, sources, text_store, params=GraphParams(depth=2, fanout=8))
    recent = filter_graph(graph, filters=[MetadataFilter("year", {"2025", "2026"})])
    for node in recent.nodes:
        print(f"community {node.community}  links {node.degree}  {node.title}")
```

- **مصادر الحواف.** يربط `EmbeddingEdgeSource` السجلات التي تتقارب عناوينها
  وملخصاتها في الذاكرة المتجهية، ويربط `MetadataEdgeSource` السجلات التي تتشارك
  الوسوم، موزونةً بمؤشر جاكار لمجموعات وسومها. ويجب أن تكون مفاتيحه ضمن
  `facet_keys` الخاصة بمخزن النصوص، وقيمتها الافتراضية
  `("categories", "authors")`. وتُضاف مفاهيم الترابط الأخرى بوصفها أصنافًا فرعية
  من `AsyncEdgeSource`. لا يستخدم أي مصدر مضمَّن الاستشهادات بعد، لكن
  `AsyncOpenAlexExtractor` يخزّن الأعمال التي تستشهد بها الورقة تحت `references`
  في بياناتها الوصفية.
- **النمو.** ينمو الرسم `depth` مستويات. يضيف كل سجل ما يصل إلى `fanout` جارًا
  لكل مصدر لا يقل وزنه عن `min_weight` (0.35 افتراضيًا)، ويُفحص `max_nodes`
  (200 افتراضيًا) قبل كل مستوى. ومع `mutual_only` (الافتراضي) لا تُبقى الحافة إلا
  إذا كان كل سجل من أقرب جيران الآخر، مما يمنع ورقة محورية من الارتباط بكل شيء.
  ولا يبقى إلا السجلات المتصلة بالبذرة.
- **المجتمعات.** تأتي `GraphNode.community` من انتشار الوسوم، وهو حتمي: الرسم
  نفسه يعطي دائمًا المجتمعات نفسها. وعندما يقطعه `max_iterations` (20 افتراضيًا)
  قبل اكتماله، تكون `DiscoveryGraph.communities_converged` مساوية لـ `False`،
  وينبغي للواجهة أن تذكر أن المجتمعات تقريبية.
- **البنية فقط.** لا تحمل العقد والحواف إحداثيات ولا ألوانًا؛ وتتولى الواجهة
  تخطيطها الخاص.
- **التصفية دون إدخال وإخراج.** `filter_graph` دالة نقية ومتزامنة، فيمكن للواجهة
  أن تعيد تشغيلها عند كل تبديل لوجه. تبقى البذرة دائمًا، وتُحذف الحواف التي تفقد
  أحد طرفيها، وتُحفظ المجتمعات لتبقى الألوان ثابتة. مرّر
  `matched_ids=await text_store.filter_ids(parse_query(...))` لإبقاء السجلات
  المطابقة لاستعلام فقط؛ ويقبل ذلك الاستدعاء النفي الخالص، مثل `NOT simulation`.
  وتقبل `filters` أيضًا كائنات `RangeFilter`، مثل `RangeFilter("year", low=2020)`.
- **الكلفة.** يولّد `EmbeddingEdgeSource` تضمين عنوان كل عقدة وملخصها، ويُصدر
  استعلامًا متجهيًا واحدًا على الأكثر لكل عقدة. ويحسب `AsyncSqliteEmbeddingStore`
  درجة كل مقطع مخزَّن في كل استعلام، لكنه يقرأ المتجهات من القرص مرة واحدة فقط،
  لذا مرّر نسخة المخزن نفسها للرسم كله، وأبقِ `max_nodes` صغيرًا مع الذاكرة
  الكبيرة.
