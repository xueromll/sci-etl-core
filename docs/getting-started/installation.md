# Installation

Python 3.10 or newer is required.

```bash
pip install "sci-etl-core[async,llm,pdf]"   # everything the Quick Start uses
pip install "sci-etl-core[full]"            # every bundled component except local embeddings
```

From a clone:

```bash
pip install -e ".[full]"
```

The base install covers configuration, both pipelines, graceful shutdown,
progress events and run metrics, the state backends, the sync adapters, HTML,
LaTeX, DOCX, and JATS XML parsing, LLM response caching, text chunking,
Boolean text search, rank fusion, discovery graphs, and the pandas processor
steps. Components load
their optional dependencies only when you import them, so add the extras for
the components you use:

| Extra | Adds | Needed for |
|-------|------|------------|
| `async` | `httpx`, `aiofiles`, `aiolimiter` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor`, `build_async_client`, `AsyncCsvUpsertExporter`, `load_config_async`, `AioLimiterRateLimiter` |
| `llm` | `openai`, `tiktoken` | `AsyncOpenAICompatibleClient`, token-based truncation |
| `pdf` | `pdfplumber` | `PdfPlumberParser` |
| `sql` | `sqlalchemy[asyncio]`, `aiosqlite` | `AsyncSqlTableExporter` |
| `viz` | `plotly`, `aiofiles` | `AsyncPlotly3DExporter` |
| `cluster` | `scikit-learn`, `numpy` | `ClusteringStep` |
| `embeddings` | `numpy`, `openai` | `AsyncOpenAIEmbedder`, the vector stores, `AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `numpy`, `sentence-transformers` | `AsyncSentenceTransformerEmbedder` |
| `search` | nothing | nothing extra: `sci_etl_core.search` needs only the standard library, so this extra just records why the package is installed |
| `dev` | pytest and plugins, `hypothesis` | running the test suite |
| `lint` | `ruff`, `mypy`, type stubs | linting and type-checking the source |
| `docs` | MkDocs, Material for MkDocs, mkdocstrings, mkdocs-click, mike, `ruff` | building this documentation site |

Importing a component whose extra is missing raises `ModuleNotFoundError`
naming the package to install.

!!! tip "Just want to run a pipeline?"
    `pip install sci-etl-cli` installs the [`sci-etl` command](../cli/index.md),
    which runs an arXiv extraction project from a YAML file with no wiring code.
