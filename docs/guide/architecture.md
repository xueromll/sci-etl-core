# Architecture

```text
ETLPipeline (blocking) --runs on a background event loop--> AsyncETLPipeline.run(query)
                                                                  |
  +---------------------------------------------------------------+
  v
AsyncExtractor.search --> parse_listing --> records not yet in AsyncStateManager
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
                          AsyncEntityExtractor.extract
                                                  |
                                                  v
                          AsyncExporter.export(entities, destination) --> mark processed

After each page: AsyncStateManager.save_metadata(last_start_index, newest-first head)
When the run ends: AsyncStateManager.flush(); RunFinished(metrics) to on_event
Throughout: ShutdownSignal stops new records; on_event receives RunStarted, PageFetched,
            RecordFinished, PageFinished

Search:    AsyncHybridSearcher.search(query) --> AsyncTextSearchStore.search (BM25) -------+--> fusion --> SearchOutcome
                                             --> AsyncSimilarArticleFinder (vector memory) -+
Discovery: build_discovery_graph(seed) --> AsyncEdgeSource.neighbours --> DiscoveryGraph --> filter_graph
Backfill:  AsyncEmbeddingStore.iter_records --> merge_passages --> AsyncTextSearchStore.index
```

## Layers

| Layer | Interface | Implementations | Import from |
|-------|-----------|-----------------|-------------|
| Extract | `AsyncExtractor` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor` | `sci_etl_core.extractors` |
| Parse | `Parser`, `TableParser` | `PdfPlumberParser`, `LatexTarballParser`, `HtmlTextParser`, `DocxParser`, `JatsXmlParser` | `sci_etl_core.parsers` |
| LLM | `AsyncLLMClient` | `AsyncOpenAICompatibleClient`, `CachingLLMClient` | `sci_etl_core.llm` |
| LLM cache | `AsyncLLMResponseCache` | `InMemoryLLMResponseCache`, `AsyncSqliteLLMResponseCache` | `sci_etl_core.llm` |
| Relevance | `AsyncRelevanceFilter` | `AsyncLLMRelevanceFilter`, `AsyncEmbeddingRelevanceFilter` | `sci_etl_core.llm` |
| Entities | `AsyncEntityExtractor` | `AsyncLLMEntityExtractor` | `sci_etl_core.llm` |
| Export | `AsyncExporter` | `AsyncCsvUpsertExporter` (list of dicts); `AsyncSqlTableExporter`, `AsyncPlotly3DExporter` (DataFrame) | `sci_etl_core.exporters` |
| State | `AsyncStateManager` | `AsyncFileStateManager`, `AsyncSqliteStateManager` | `sci_etl_core.state` |
| Embeddings | `AsyncEmbedder` | `AsyncOpenAIEmbedder`, `AsyncSentenceTransformerEmbedder` | `sci_etl_core.embeddings` |
| Chunking | `TextChunker` | `SlidingWindowChunker` | `sci_etl_core.embeddings` |
| Vector memory | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`, `AsyncSqliteEmbeddingStore` | `sci_etl_core.embeddings` |
| Memory ingest | `MemoryIngestor` | `AsyncChunkIngestor`, `AsyncSearchIndexer`, `AsyncCompositeIngestor` | `sci_etl_core.embeddings`, `sci_etl_core.search`, `sci_etl_core` |
| Text search | `AsyncTextSearchStore` | `InMemoryTextSearchStore`, `AsyncSqliteFts5Store`; `MetadataFilter`, `RangeFilter`; `backfill_text_index` | `sci_etl_core.search` |
| Fusion | `FusionStrategy` | `reciprocal_rank_fusion`, `normalized_score_fusion`; `AsyncHybridSearcher` | `sci_etl_core.search` |
| Discovery graph | `AsyncEdgeSource` | `EmbeddingEdgeSource`, `MetadataEdgeSource`; `build_discovery_graph`, `filter_graph` | `sci_etl_core.search` |
| Post-processing | `Processor`, `RecordValidator` | `ProcessorChain`, `NormalizationStep`, `DeduplicationStep`, `ClusteringStep`, `CompletenessStep`, `QualityFlagStep`, `ValueClipStep`, `TableLayoutStep`; `NumericRangeValidator`, `KeywordExclusionValidator`, `CompositeValidator` | `sci_etl_core.processors` |
| Sync adapters | `Extractor`, `RelevanceFilter`, `EntityExtractor`, `LLMClient`, `Exporter`, `StateManager` | `Sync*Adapter` for each | `sci_etl_core` |
| Orchestration | — | `AsyncETLPipeline`, `ETLPipeline` | `sci_etl_core` |

The pipelines, stage interfaces, adapters, and most implementations are also
re-exported from `sci_etl_core` itself; parser implementations, processor
steps, and validators come from their subpackages. Supporting modules:
`sci_etl_core.config`, `sci_etl_core.http_async` (`build_async_client`),
`sci_etl_core.rate_limiter` (including `HostRateLimiter`),
`sci_etl_core.signals`, `sci_etl_core.observability` (progress events and
`RunMetrics`), `sci_etl_core.log_utils`, `sci_etl_core.exceptions`, and
`sci_etl_core.discovery` (the read-model for user interfaces). Every package loads its public names on first access, so
importing one component never requires another component's optional
dependencies.

The [API reference](../reference/index.md) documents each module in detail.
