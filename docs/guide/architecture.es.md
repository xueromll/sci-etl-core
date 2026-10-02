# Arquitectura

```text
ETLPipeline (bloqueante) --se ejecuta en un bucle de eventos en segundo plano--> AsyncETLPipeline.run(query)
                                                                  |
  +---------------------------------------------------------------+
  v
AsyncExtractor.fetch_page(cursor) --> ListingPage --> registros ni procesados ni en cuarentena
                                                  |  (max_concurrency a la vez)
                                                  v
                          AsyncRelevanceFilter.is_relevant --no--> marcar como procesado
                                                  | sí
                                                  v
                          AsyncExtractor.fetch_full_text (mejor fuente -> resumen)
                                                  |
                                                  +--> MemoryIngestor (opcional)
                                                  |      AsyncChunkIngestor: TextChunker -> AsyncEmbedder
                                                  |        -> AsyncEmbeddingStore
                                                  |      AsyncSearchIndexer: AsyncTextSearchStore
                                                  |      AsyncCompositeIngestor: varios a la vez
                                                  v
                          AsyncEntityExtractor.extract_record(record, text)
                                                  |      (entidades tipadas; rechazos con motivos)
                                                  v
                          AsyncExporter.write(record, entities) --durable_writes--> marcar como procesado

Antes de la primera página: AsyncExporter.open()
Después de cada página: AsyncExporter.flush() --> marcar los registros que hizo duraderos;
                 intentos fallidos -> AsyncStateManager.record_failure (R18);
                 AsyncStateManager.save_metadata(cursor, truncated, cabecera newest-first)
Al terminar la ejecución: AsyncExporter.flush(), AsyncExporter.aclose(), AsyncStateManager.flush();
                   RunFinished(metrics) -> on_event
Durante toda la ejecución: ShutdownSignal detiene los registros nuevos; on_event recibe
            RunStarted, PageFetched, RecordFinished, PageFinished

Search:    AsyncHybridSearcher.search(query) --> AsyncTextSearchStore.search (BM25) -------+--> fusion --> SearchOutcome
                                             --> AsyncSimilarArticleFinder (vector memory) -+
Discovery: build_discovery_graph(seed) --> AsyncEdgeSource.neighbours --> DiscoveryGraph --> filter_graph
Backfill:  AsyncEmbeddingStore.iter_records --> merge_passages --> AsyncTextSearchStore.index
```

## Capas {#layers}

| Capa | Interfaz | Implementaciones | Importar desde |
|------|----------|------------------|----------------|
| Extracción | `AsyncExtractor` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor` | `sci_etl_core.extractors` |
| Análisis | `Parser`, `TableParser` | `PdfPlumberParser`, `LatexTarballParser`, `HtmlTextParser`, `DocxParser`, `JatsXmlParser` | `sci_etl_core.parsers` |
| LLM | `AsyncLLMClient` | `AsyncOpenAICompatibleClient`, `CachingLLMClient` | `sci_etl_core.llm` |
| Caché del LLM | `AsyncLLMResponseCache` | `InMemoryLLMResponseCache`, `AsyncSqliteLLMResponseCache` | `sci_etl_core.llm` |
| Relevancia | `AsyncRelevanceFilter` | `AsyncLLMRelevanceFilter`, `AsyncEmbeddingRelevanceFilter` | `sci_etl_core.llm` |
| Entidades | `AsyncEntityExtractor` | `AsyncLLMEntityExtractor` (diccionarios, o modelos de Pydantic con `schema=`) | `sci_etl_core.llm` |
| Exportación | `AsyncExporter` | `AsyncCsvExporter`, `AsyncJsonlExporter`, `AsyncClaimStoreExporter` | `sci_etl_core.exporters`, `sci_etl_core.claims` |
| Afirmaciones (provisional) | `AsyncClaimStore`, `AsyncRejectionStore` | `AsyncLLMClaimExtractor`; `InMemoryClaimStore`, `AsyncSqliteClaimStore`; `InMemoryRejectionStore`, `AsyncSqliteRejectionStore`; `locate_quote` | `sci_etl_core.claims` |
| Estado | `AsyncStateManager` | `AsyncFileStateManager`, `AsyncSqliteStateManager` | `sci_etl_core.state` |
| Embeddings | `AsyncEmbedder` | `AsyncOpenAIEmbedder`, `AsyncSentenceTransformerEmbedder` | `sci_etl_core.embeddings` |
| Fragmentación | `TextChunker` | `SlidingWindowChunker` | `sci_etl_core.embeddings` |
| Memoria vectorial | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`, `AsyncSqliteEmbeddingStore` | `sci_etl_core.embeddings` |
| Ingesta en memoria | `MemoryIngestor` | `AsyncChunkIngestor`, `AsyncSearchIndexer`, `AsyncCompositeIngestor` | `sci_etl_core.embeddings`, `sci_etl_core.search`, `sci_etl_core` |
| Búsqueda de texto | `AsyncTextSearchStore` | `InMemoryTextSearchStore`, `AsyncSqliteFts5Store`; `MetadataFilter`, `RangeFilter`; `backfill_text_index` | `sci_etl_core.search` |
| Fusión | `FusionStrategy` | `reciprocal_rank_fusion`, `normalized_score_fusion`; `AsyncHybridSearcher` | `sci_etl_core.search` |
| Grafo de descubrimiento | `AsyncEdgeSource` | `EmbeddingEdgeSource`, `MetadataEdgeSource`; `build_discovery_graph`, `filter_graph` | `sci_etl_core.search` |
| Posprocesamiento | `Processor`, `RecordValidator` | `ProcessorChain`, `NormalizationStep`, `DeduplicationStep`, `ClusteringStep`, `CompletenessStep`, `QualityFlagStep`, `ValueClipStep`, `TableLayoutStep`; `NumericRangeValidator`, `KeywordExclusionValidator`, `CompositeValidator` | `sci_etl_core.processors` |
| Sumideros de tablas | `TableSink` | `SqlTableSink`, `Plotly3DSink` | `sci_etl_core.processors.sinks` |
| Orquestación | — | `AsyncETLPipeline`, `ETLPipeline` | `sci_etl_core` |

Los pipelines, las interfaces de las etapas y la mayoría de las
implementaciones también se reexportan desde el propio `sci_etl_core`; las
implementaciones de analizadores, los pasos de procesadores, los validadores y
las afirmaciones se importan desde sus subpaquetes. Módulos de apoyo:
`sci_etl_core.config`, `sci_etl_core.http_async` (`build_async_client`),
`sci_etl_core.rate_limiter` (incluido `HostRateLimiter`),
`sci_etl_core.signals`, `sci_etl_core.observability` (eventos de progreso y
`RunMetrics`), `sci_etl_core.exceptions` y `sci_etl_core.discovery` (el modelo
de lectura para interfaces de usuario). Todos los módulos registran mensajes a
través del módulo estándar `logging`; consulta [Registro](logging.md). Cada
paquete carga sus nombres públicos en el primer acceso, así que importar un
componente nunca requiere las dependencias opcionales de otro.

La [referencia de la API](../reference/index.md) documenta cada módulo en
detalle.
