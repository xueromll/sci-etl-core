# API reference

These pages are generated from the docstrings and type annotations in the
source. Each page documents the modules that define the names; import them from
the package named at the top of the page, not from the defining module, since
module layout inside a package may change between releases.

| Page | Package | Covers |
|------|---------|--------|
| [Pipelines](pipelines.md) | `sci_etl_core` | `AsyncETLPipeline`, `ETLPipeline`, memory ingestion, `ShutdownSignal`, progress events and `RunMetrics` |
| [Configuration](configuration.md) | `sci_etl_core` | `BaseAppConfig` and its sections, `load_config`, `load_config_async` |
| [Models and exceptions](models.md) | `sci_etl_core` | `RawRecord`, `TokenUsage`, the `SciEtlError` hierarchy, the discovery read-model |
| [Extractors](extractors.md) | `sci_etl_core.extractors` | `AsyncExtractor`, the arXiv, PubMed, Semantic Scholar, and OpenAlex extractors |
| [Parsers](parsers.md) | `sci_etl_core.parsers` | PDF, LaTeX, HTML, DOCX, and JATS XML parsers, reference trimming |
| [LLM](llm.md) | `sci_etl_core.llm` | LLM clients, response caching, relevance filters, entity extractors and typed schemas |
| [Embeddings](embeddings.md) | `sci_etl_core.embeddings` | embedders, chunking, vector stores, similarity search |
| [Search](search.md) | `sci_etl_core.search` | query language, text stores, fusion, hybrid search, discovery graphs |
| [Exporters](exporters.md) | `sci_etl_core.exporters` | the exporter lifecycle, CSV and JSON Lines exporters |
| [Claims](claims.md) | `sci_etl_core.claims` | claims, evidence spans, stamps, claim and rejection stores, the claim extractor and exporter (provisional) |
| [Processors](processors.md) | `sci_etl_core.processors` | DataFrame steps, key normalizers, record validators and their violations, table sinks |
| [State](state.md) | `sci_etl_core.state` | file and SQLite state managers |
| [Utilities](utilities.md) | defining module | HTTP clients, rate limiters, including per-host limits |

For how the pieces fit together, see [Architecture](../guide/architecture.md).
