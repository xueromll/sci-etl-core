# 架构

```text
ETLPipeline（阻塞式） --在后台事件循环上运行--> AsyncETLPipeline.run(query)
                                                                  |
  +---------------------------------------------------------------+
  v
AsyncExtractor.fetch_page(cursor) --> ListingPage --> 既未处理也未被隔离的记录
                                                  |  （同时最多 max_concurrency 条）
                                                  v
                          AsyncRelevanceFilter.is_relevant --否--> 标记为已处理
                                                  | 是
                                                  v
                          AsyncExtractor.fetch_full_text（最佳来源 -> 摘要）
                                                  |
                                                  +--> MemoryIngestor（可选）
                                                  |      AsyncChunkIngestor: TextChunker -> AsyncEmbedder
                                                  |        -> AsyncEmbeddingStore
                                                  |      AsyncSearchIndexer: AsyncTextSearchStore
                                                  |      AsyncCompositeIngestor: 同时使用多个
                                                  v
                          AsyncEntityExtractor.extract_record(record, text)
                                                  |      （类型化实体；带原因的拒绝记录）
                                                  v
                          AsyncExporter.write(record, entities) --durable_writes--> 标记为已处理

第一页之前：AsyncExporter.open()
每页之后：AsyncExporter.flush() --> 标记由它持久化的记录；
                 失败的尝试 -> AsyncStateManager.record_failure (R18)；
                 AsyncStateManager.save_metadata（游标、truncated、newest-first 列表头）
运行结束时：AsyncExporter.flush()、AsyncExporter.aclose()、AsyncStateManager.flush()；
                   RunFinished(metrics) -> on_event
整个运行期间：ShutdownSignal 阻止开始新记录；on_event 接收
            RunStarted、PageFetched、RecordFinished、PageFinished

Search:    AsyncHybridSearcher.search(query) --> AsyncTextSearchStore.search (BM25) -------+--> fusion --> SearchOutcome
                                             --> AsyncSimilarArticleFinder (vector memory) -+
Discovery: build_discovery_graph(seed) --> AsyncEdgeSource.neighbours --> DiscoveryGraph --> filter_graph
Backfill:  AsyncEmbeddingStore.iter_records --> merge_passages --> AsyncTextSearchStore.index
```

## 分层 {#layers}

| 层 | 接口 | 实现 | 导入位置 |
|----|------|------|----------|
| 提取 | `AsyncExtractor` | `AsyncArxivExtractor`、`AsyncPubMedExtractor`、`AsyncSemanticScholarExtractor`、`AsyncOpenAlexExtractor` | `sci_etl_core.extractors` |
| 解析 | `Parser`、`TableParser` | `PdfPlumberParser`、`LatexTarballParser`、`HtmlTextParser`、`DocxParser`、`JatsXmlParser` | `sci_etl_core.parsers` |
| LLM | `AsyncLLMClient` | `AsyncOpenAICompatibleClient`、`CachingLLMClient` | `sci_etl_core.llm` |
| LLM 缓存 | `AsyncLLMResponseCache` | `InMemoryLLMResponseCache`、`AsyncSqliteLLMResponseCache` | `sci_etl_core.llm` |
| 相关性 | `AsyncRelevanceFilter` | `AsyncLLMRelevanceFilter`、`AsyncEmbeddingRelevanceFilter` | `sci_etl_core.llm` |
| 实体 | `AsyncEntityExtractor` | `AsyncLLMEntityExtractor`（字典，或通过 `schema=` 使用 Pydantic 模型） | `sci_etl_core.llm` |
| 导出 | `AsyncExporter` | `AsyncCsvExporter`、`AsyncJsonlExporter`、`AsyncClaimStoreExporter` | `sci_etl_core.exporters`、`sci_etl_core.claims` |
| 论断（临时性 API） | `AsyncClaimStore`、`AsyncRejectionStore` | `AsyncLLMClaimExtractor`；`InMemoryClaimStore`、`AsyncSqliteClaimStore`；`InMemoryRejectionStore`、`AsyncSqliteRejectionStore`；`locate_quote` | `sci_etl_core.claims` |
| 状态 | `AsyncStateManager` | `AsyncFileStateManager`、`AsyncSqliteStateManager` | `sci_etl_core.state` |
| 嵌入 | `AsyncEmbedder` | `AsyncOpenAIEmbedder`、`AsyncSentenceTransformerEmbedder` | `sci_etl_core.embeddings` |
| 分块 | `TextChunker` | `SlidingWindowChunker` | `sci_etl_core.embeddings` |
| 向量记忆 | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`、`AsyncSqliteEmbeddingStore` | `sci_etl_core.embeddings` |
| 记忆摄取 | `MemoryIngestor` | `AsyncChunkIngestor`、`AsyncSearchIndexer`、`AsyncCompositeIngestor` | `sci_etl_core.embeddings`、`sci_etl_core.search`、`sci_etl_core` |
| 文本检索 | `AsyncTextSearchStore` | `InMemoryTextSearchStore`、`AsyncSqliteFts5Store`；`MetadataFilter`、`RangeFilter`；`backfill_text_index` | `sci_etl_core.search` |
| 融合 | `FusionStrategy` | `reciprocal_rank_fusion`、`normalized_score_fusion`；`AsyncHybridSearcher` | `sci_etl_core.search` |
| 发现图 | `AsyncEdgeSource` | `EmbeddingEdgeSource`、`MetadataEdgeSource`；`build_discovery_graph`、`filter_graph` | `sci_etl_core.search` |
| 后处理 | `Processor`、`RecordValidator` | `ProcessorChain`、`NormalizationStep`、`DeduplicationStep`、`ClusteringStep`、`CompletenessStep`、`QualityFlagStep`、`ValueClipStep`、`TableLayoutStep`；`NumericRangeValidator`、`KeywordExclusionValidator`、`CompositeValidator` | `sci_etl_core.processors` |
| 表格输出端 | `TableSink` | `SqlTableSink`、`Plotly3DSink` | `sci_etl_core.processors.sinks` |
| 编排 | — | `AsyncETLPipeline`、`ETLPipeline` | `sci_etl_core` |

流水线、各阶段接口以及大多数实现也从 `sci_etl_core` 本身重新导出；解析器实现、处理器步骤、
校验器和论断则从各自的子包导入。辅助模块有：`sci_etl_core.config`、
`sci_etl_core.http_async`（`build_async_client`）、`sci_etl_core.rate_limiter`（包括
`HostRateLimiter`）、`sci_etl_core.signals`、`sci_etl_core.observability`（进度事件和
`RunMetrics`）、`sci_etl_core.exceptions` 以及 `sci_etl_core.discovery`（供用户界面使用的
读模型）。每个模块都通过标准 `logging` 模块输出日志；参见[日志](logging.md)。每个包在首次
访问时才加载其公开名称，因此导入一个组件永远不需要另一个组件的可选依赖。

[API 参考](../reference/index.md)详细记录了每个模块。
