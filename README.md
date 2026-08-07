# sci-etl-core

Domain-agnostic ETL toolkit for scientific text mining pipelines: fetch
records from a source, filter for relevance, extract structured entities
with an LLM, process the results (normalize, deduplicate, cluster, flag
quality), and export them — all through dependency-injected interfaces
with no hard-coded domain knowledge.

## Install

```bash
pip install -e /path/to/sci-etl-core
```

## Layers

| Layer        | Abstract class            | Ships with                                  |
|--------------|----------------------------|----------------------------------------------|
| Extraction   | `Extractor`                 | `ArxivExtractor`                              |
| Parsing      | `Parser`, `TableParser`      | `PdfPlumberParser`, `HtmlTextParser`, `LatexTarballParser` |
| LLM          | `LLMClient`                 | `OpenAICompatibleClient` (DeepSeek/OpenAI-compatible) |
| Relevance    | `RelevanceFilter`            | `LLMRelevanceFilter`                          |
| Extraction   | `EntityExtractor`            | `LLMEntityExtractor`                          |
| Processing   | `Processor`, `ProcessorChain`| `NormalizationStep`, `DeduplicationStep`, `ClusteringStep`, `CompletenessStep`, `QualityFlagStep` |
| Export       | `Exporter`                   | `CsvUpsertExporter`, `Plotly3DExporter`, `SqlTableExporter` |
| State        | `StateManager`               | `FileStateManager`                            |
| Orchestration| —                             | `ETLPipeline`                                 |

Nothing in this package references any specific scientific domain. Every
domain concept (galaxy names, sky coordinates, drug identifiers, patent
classes, ...) is supplied by the host project through subclasses or
configuration.

See `MIGRATION.md` for a worked example adapting `udg-catalogue`.
