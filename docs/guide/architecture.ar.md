# البنية

```text
ETLPipeline (blocking) --runs on a background event loop--> AsyncETLPipeline.run(query)
                                                                  |
  +---------------------------------------------------------------+
  v
AsyncExtractor.fetch_page(cursor) --> ListingPage --> records neither processed nor quarantined
                                                  |  (max_concurrency at a time)
                                                  v
                          AsyncRelevanceFilter.is_relevant --no--> mark processed
                                                  | yes
                                                  v
                          AsyncExtractor.fetch_full_text (best source -> abstract)
                                                  |
                                                  +--> MemoryIngestor (optional)
                                                  |      AsyncChunkIngestor: TextChunker -> AsyncEmbedder
                                                  |        -> AsyncEmbeddingStore
                                                  |      AsyncSearchIndexer: AsyncTextSearchStore
                                                  |      AsyncCompositeIngestor: several at once
                                                  v
                          AsyncEntityExtractor.extract_record(record, text)
                                                  |      (typed entities; rejections with reasons)
                                                  v
                          AsyncExporter.write(record, entities) --durable_writes--> mark processed

Before the first page: AsyncExporter.open()
After each page: AsyncExporter.flush() --> mark the records it made durable;
                 failed attempts to AsyncStateManager.record_failure (R18);
                 AsyncStateManager.save_metadata(cursor, truncated, newest-first head)
When the run ends: AsyncExporter.flush(), AsyncExporter.aclose(), AsyncStateManager.flush();
                   RunFinished(metrics) to on_event
Throughout: ShutdownSignal stops new records; on_event receives RunStarted, PageFetched,
            RecordFinished, PageFinished

Search:    AsyncHybridSearcher.search(query) --> AsyncTextSearchStore.search (BM25) -------+--> fusion --> SearchOutcome
                                             --> AsyncSimilarArticleFinder (vector memory) -+
Discovery: build_discovery_graph(seed) --> AsyncEdgeSource.neighbours --> DiscoveryGraph --> filter_graph
Backfill:  AsyncEmbeddingStore.iter_records --> merge_passages --> AsyncTextSearchStore.index
```

يبقى المخطط أعلاه بالإنجليزية كي يحافظ على محاذاته من اليسار إلى اليمين. وهذا ما
يصفه: يشغّل `ETLPipeline` المتزامن `AsyncETLPipeline.run` على حلقة أحداث خلفية.
يجلب المستخرِج صفحة من القائمة، وتُعالَج سجلاتها غير المعالَجة وغير المحجورة، بحد
أقصى `max_concurrency` سجلًا في الوقت نفسه. يقرر مرشح الصلة أولًا ما إذا كان السجل
ذا صلة؛ فإن لم يكن عُلِّم معالَجًا فورًا. وإلا جُلب نصه الكامل (أفضل مصدر، ثم
الملخص)، ومُرِّر اختياريًا إلى مستوعِب الذاكرة، ثم استخرج مستخرِج الكيانات منه
كيانات منمّطة مع أسباب ما رُفض منها، وكتبها المصدِّر. ولا يُعلَّم السجل معالَجًا إلا
بعد أن تصير كياناته دائمة. يُفتح المصدِّر قبل الصفحة الأولى، ويُفرَّغ بعد كل صفحة،
وتُحفظ الحالة والمؤشر، وفي نهاية التشغيل يُفرَّغ المصدِّر ويُغلق وتُحفظ الحالة.
وتُظهر الأسطر الثلاثة الأخيرة مسارات البحث الهجين ورسوم الاستكشاف والملء من الذاكرة
المتجهية.

## الطبقات {#layers}

| الطبقة | الواجهة | التطبيقات | الاستيراد من |
|--------|---------|-----------|--------------|
| الاستخراج | `AsyncExtractor` | `AsyncArxivExtractor`، `AsyncPubMedExtractor`، `AsyncSemanticScholarExtractor`، `AsyncOpenAlexExtractor` | `sci_etl_core.extractors` |
| التحليل | `Parser`، `TableParser` | `PdfPlumberParser`، `LatexTarballParser`، `HtmlTextParser`، `DocxParser`، `JatsXmlParser` | `sci_etl_core.parsers` |
| النموذج اللغوي | `AsyncLLMClient` | `AsyncOpenAICompatibleClient`، `CachingLLMClient` | `sci_etl_core.llm` |
| ذاكرة التخزين المؤقت للنموذج اللغوي | `AsyncLLMResponseCache` | `InMemoryLLMResponseCache`، `AsyncSqliteLLMResponseCache` | `sci_etl_core.llm` |
| الصلة | `AsyncRelevanceFilter` | `AsyncLLMRelevanceFilter`، `AsyncEmbeddingRelevanceFilter` | `sci_etl_core.llm` |
| الكيانات | `AsyncEntityExtractor` | `AsyncLLMEntityExtractor` (قواميس، أو نماذج Pydantic مع `schema=`) | `sci_etl_core.llm` |
| التصدير | `AsyncExporter` | `AsyncCsvExporter`، `AsyncJsonlExporter`، `AsyncClaimStoreExporter` | `sci_etl_core.exporters`، `sci_etl_core.claims` |
| الادعاءات (مؤقتة) | `AsyncClaimStore`، `AsyncRejectionStore` | `AsyncLLMClaimExtractor`؛ `InMemoryClaimStore`، `AsyncSqliteClaimStore`؛ `InMemoryRejectionStore`، `AsyncSqliteRejectionStore`؛ `locate_quote` | `sci_etl_core.claims` |
| الحالة | `AsyncStateManager` | `AsyncFileStateManager`، `AsyncSqliteStateManager` | `sci_etl_core.state` |
| التضمينات | `AsyncEmbedder` | `AsyncOpenAIEmbedder`، `AsyncSentenceTransformerEmbedder` | `sci_etl_core.embeddings` |
| التقطيع | `TextChunker` | `SlidingWindowChunker` | `sci_etl_core.embeddings` |
| الذاكرة المتجهية | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`، `AsyncSqliteEmbeddingStore` | `sci_etl_core.embeddings` |
| الاستيعاب في الذاكرة | `MemoryIngestor` | `AsyncChunkIngestor`، `AsyncSearchIndexer`، `AsyncCompositeIngestor` | `sci_etl_core.embeddings`، `sci_etl_core.search`، `sci_etl_core` |
| البحث النصي | `AsyncTextSearchStore` | `InMemoryTextSearchStore`، `AsyncSqliteFts5Store`؛ `MetadataFilter`، `RangeFilter`؛ `backfill_text_index` | `sci_etl_core.search` |
| الدمج | `FusionStrategy` | `reciprocal_rank_fusion`، `normalized_score_fusion`؛ `AsyncHybridSearcher` | `sci_etl_core.search` |
| رسم الاستكشاف البياني | `AsyncEdgeSource` | `EmbeddingEdgeSource`، `MetadataEdgeSource`؛ `build_discovery_graph`، `filter_graph` | `sci_etl_core.search` |
| المعالجة اللاحقة | `Processor`، `RecordValidator` | `ProcessorChain`، `NormalizationStep`، `DeduplicationStep`، `ClusteringStep`، `CompletenessStep`، `QualityFlagStep`، `ValueClipStep`، `TableLayoutStep`؛ `NumericRangeValidator`، `KeywordExclusionValidator`، `CompositeValidator` | `sci_etl_core.processors` |
| مصارف الجداول | `TableSink` | `SqlTableSink`، `Plotly3DSink` | `sci_etl_core.processors.sinks` |
| التنسيق | — | `AsyncETLPipeline`، `ETLPipeline` | `sci_etl_core` |

يُعاد تصدير خطوط المعالجة وواجهات المراحل ومعظم التطبيقات من `sci_etl_core` نفسه
أيضًا؛ أما تطبيقات المحلِّلات وخطوات المعالِجات والمدقّقات والادعاءات فتُستورد من
حزمها الفرعية. الوحدات المساندة: `sci_etl_core.config`، و`sci_etl_core.http_async`
(`build_async_client`)، و`sci_etl_core.rate_limiter` (بما فيها `HostRateLimiter`)،
و`sci_etl_core.signals`، و`sci_etl_core.observability` (أحداث التقدم و`RunMetrics`)،
و`sci_etl_core.exceptions`، و`sci_etl_core.discovery` (نموذج القراءة لواجهات
المستخدم). تسجّل كل وحدة رسائلها عبر الوحدة القياسية `logging`؛ راجع
[التسجيل](logging.md). وتحمّل كل حزمة أسماءها العامة عند أول وصول إليها، فلا يتطلب
استيراد مكوّن واحد أبدًا الاعتماديات الاختيارية لمكوّن آخر.

يوثّق [مرجع الواجهة البرمجية](../reference/index.md) كل وحدة بالتفصيل.
