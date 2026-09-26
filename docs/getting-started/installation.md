# Installation

Python 3.11 or newer is required.

```bash
pip install "sci-etl-core[async,arxiv,llm,pdf]"   # everything the Quick Start uses
pip install "sci-etl-core[full]"                  # every bundled component except local embeddings
```

From a clone:

```bash
pip install -e ".[full]"
```

The base install requires only Pydantic. It covers both pipelines, graceful
shutdown, progress events and run metrics, the component contracts, the
configuration models, the state backends, LLM response caching, the CSV and
JSON Lines exporters, claims and provenance, record validators, LaTeX parsing,
text chunking, Boolean text search, rank fusion, and discovery graphs. A
component that needs another package imports it when you import the
component, so add the extras for the components you use:

| Extra | Adds | Needed for |
|-------|------|------------|
| `config` | `pyyaml`, `python-dotenv` | `load_config`, `load_config_async`, `load_yaml` |
| `async` | `httpx`, `aiolimiter` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor`, `build_async_client`, `AioLimiterRateLimiter` |
| `arxiv` | `beautifulsoup4`, `lxml` | `AsyncArxivExtractor`, which also needs `async` |
| `xml` | `lxml` | `JatsXmlParser`, `DocxParser`, and `AsyncPubMedExtractor`, which also needs `async` |
| `html` | `beautifulsoup4` | `HtmlTextParser`, which `AsyncLLMEntityExtractor` uses by default for full text that starts with markup |
| `processors` | `pandas`, `numpy` | every step in `sci_etl_core.processors` except the validators, and the table sinks |
| `llm` | `openai`, `tiktoken` | `AsyncOpenAICompatibleClient`, token-based truncation |
| `pdf` | `pdfplumber` | `PdfPlumberParser` |
| `sql` | `sqlalchemy` | `SqlTableSink`, which also needs `processors` |
| `viz` | `plotly` | `Plotly3DSink`, which also needs `processors` |
| `cluster` | `scikit-learn`, `numpy` | `ClusteringStep`, which also needs `processors` |
| `embeddings` | `numpy`, `openai` | `AsyncOpenAIEmbedder`, the vector stores, `AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `numpy`, `sentence-transformers` | `AsyncSentenceTransformerEmbedder` |
| `search` | nothing | nothing extra: `sci_etl_core.search` needs only the standard library, so this extra just records why the package is installed |
| `full` | every package above except `sentence-transformers` | every bundled component except local embeddings |
| `dev` | pytest and plugins, `hypothesis` | running the test suite |
| `lint` | `ruff`, `mypy`, type stubs | linting and type-checking the source |
| `docs` | MkDocs, Material for MkDocs, mkdocstrings, mkdocs-click, mike, `ruff` | building this documentation site |

Importing a component whose extra is missing raises `ModuleNotFoundError`
naming the package to install.

!!! tip "Just want to run a pipeline?"
    `pip install sci-etl-cli` installs the [`sci-etl` command](../cli/index.md),
    which runs an arXiv extraction project from a YAML file with no wiring code.
