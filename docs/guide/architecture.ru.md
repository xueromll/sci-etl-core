# Архитектура

```text
ETLPipeline (блокирующий) --выполняется в фоновом цикле событий--> AsyncETLPipeline.run(query)
                                                                  |
  +---------------------------------------------------------------+
  v
AsyncExtractor.fetch_page(cursor) --> ListingPage --> записи, не обработанные и не в карантине
                                                  |  (не более max_concurrency одновременно)
                                                  v
                          AsyncRelevanceFilter.is_relevant --нет--> пометить как обработанную
                                                  | да
                                                  v
                          AsyncExtractor.fetch_full_text (лучший источник -> аннотация)
                                                  |
                                                  +--> MemoryIngestor (необязательно)
                                                  |      AsyncChunkIngestor: TextChunker -> AsyncEmbedder
                                                  |        -> AsyncEmbeddingStore
                                                  |      AsyncSearchIndexer: AsyncTextSearchStore
                                                  |      AsyncCompositeIngestor: несколько сразу
                                                  v
                          AsyncEntityExtractor.extract_record(record, text)
                                                  |      (типизированные сущности; отклонения с причинами)
                                                  v
                          AsyncExporter.write(record, entities) --durable_writes--> пометить как обработанную

Перед первой страницей: AsyncExporter.open()
После каждой страницы: AsyncExporter.flush() --> пометить записи, которые он надёжно сохранил;
                 неудачные попытки -> AsyncStateManager.record_failure (R18);
                 AsyncStateManager.save_metadata(курсор, truncated, голова листинга newest-first)
По окончании запуска: AsyncExporter.flush(), AsyncExporter.aclose(), AsyncStateManager.flush();
                   RunFinished(metrics) -> on_event
На протяжении всего запуска: ShutdownSignal останавливает новые записи; on_event получает
            RunStarted, PageFetched, RecordFinished, PageFinished

Search:    AsyncHybridSearcher.search(query) --> AsyncTextSearchStore.search (BM25) -------+--> fusion --> SearchOutcome
                                             --> AsyncSimilarArticleFinder (vector memory) -+
Discovery: build_discovery_graph(seed) --> AsyncEdgeSource.neighbours --> DiscoveryGraph --> filter_graph
Backfill:  AsyncEmbeddingStore.iter_records --> merge_passages --> AsyncTextSearchStore.index
```

## Слои {#layers}

| Слой | Интерфейс | Реализации | Откуда импортировать |
|------|-----------|------------|----------------------|
| Извлечение | `AsyncExtractor` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor` | `sci_etl_core.extractors` |
| Разбор | `Parser`, `TableParser` | `PdfPlumberParser`, `LatexTarballParser`, `HtmlTextParser`, `DocxParser`, `JatsXmlParser` | `sci_etl_core.parsers` |
| LLM | `AsyncLLMClient` | `AsyncOpenAICompatibleClient`, `CachingLLMClient` | `sci_etl_core.llm` |
| Кэш LLM | `AsyncLLMResponseCache` | `InMemoryLLMResponseCache`, `AsyncSqliteLLMResponseCache` | `sci_etl_core.llm` |
| Релевантность | `AsyncRelevanceFilter` | `AsyncLLMRelevanceFilter`, `AsyncEmbeddingRelevanceFilter` | `sci_etl_core.llm` |
| Сущности | `AsyncEntityExtractor` | `AsyncLLMEntityExtractor` (словари или модели Pydantic с `schema=`) | `sci_etl_core.llm` |
| Экспорт | `AsyncExporter` | `AsyncCsvExporter`, `AsyncJsonlExporter`, `AsyncClaimStoreExporter` | `sci_etl_core.exporters`, `sci_etl_core.claims` |
| Утверждения (предварительный API) | `AsyncClaimStore`, `AsyncRejectionStore` | `AsyncLLMClaimExtractor`; `InMemoryClaimStore`, `AsyncSqliteClaimStore`; `InMemoryRejectionStore`, `AsyncSqliteRejectionStore`; `locate_quote` | `sci_etl_core.claims` |
| Состояние | `AsyncStateManager` | `AsyncFileStateManager`, `AsyncSqliteStateManager` | `sci_etl_core.state` |
| Эмбеддинги | `AsyncEmbedder` | `AsyncOpenAIEmbedder`, `AsyncSentenceTransformerEmbedder` | `sci_etl_core.embeddings` |
| Разбиение на чанки | `TextChunker` | `SlidingWindowChunker` | `sci_etl_core.embeddings` |
| Векторная память | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`, `AsyncSqliteEmbeddingStore` | `sci_etl_core.embeddings` |
| Загрузка в память | `MemoryIngestor` | `AsyncChunkIngestor`, `AsyncSearchIndexer`, `AsyncCompositeIngestor` | `sci_etl_core.embeddings`, `sci_etl_core.search`, `sci_etl_core` |
| Текстовый поиск | `AsyncTextSearchStore` | `InMemoryTextSearchStore`, `AsyncSqliteFts5Store`; `MetadataFilter`, `RangeFilter`; `backfill_text_index` | `sci_etl_core.search` |
| Слияние | `FusionStrategy` | `reciprocal_rank_fusion`, `normalized_score_fusion`; `AsyncHybridSearcher` | `sci_etl_core.search` |
| Граф связанных статей | `AsyncEdgeSource` | `EmbeddingEdgeSource`, `MetadataEdgeSource`; `build_discovery_graph`, `filter_graph` | `sci_etl_core.search` |
| Постобработка | `Processor`, `RecordValidator` | `ProcessorChain`, `NormalizationStep`, `DeduplicationStep`, `ClusteringStep`, `CompletenessStep`, `QualityFlagStep`, `ValueClipStep`, `TableLayoutStep`; `NumericRangeValidator`, `KeywordExclusionValidator`, `CompositeValidator` | `sci_etl_core.processors` |
| Стоки таблиц | `TableSink` | `SqlTableSink`, `Plotly3DSink` | `sci_etl_core.processors.sinks` |
| Оркестрация | — | `AsyncETLPipeline`, `ETLPipeline` | `sci_etl_core` |

Пайплайны, интерфейсы этапов и большинство реализаций также реэкспортируются
из самого `sci_etl_core`; реализации парсеров, шаги процессоров, валидаторы и
утверждения импортируются из своих подпакетов. Вспомогательные модули:
`sci_etl_core.config`, `sci_etl_core.http_async` (`build_async_client`),
`sci_etl_core.rate_limiter` (включая `HostRateLimiter`),
`sci_etl_core.signals`, `sci_etl_core.observability` (события прогресса и
`RunMetrics`), `sci_etl_core.exceptions` и `sci_etl_core.discovery` (модель
чтения для пользовательских интерфейсов). Каждый модуль пишет журнал через
стандартный модуль `logging`; см. [Журналирование](logging.md). Каждый пакет
загружает свои публичные имена при первом обращении, поэтому импорт одного
компонента никогда не требует необязательных зависимостей другого.

[Справочник API](../reference/index.md) подробно документирует каждый модуль.
