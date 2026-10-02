# sci-etl-core

[![CI](https://github.com/xueromll/sci-etl-core/actions/workflows/ci.yml/badge.svg)](https://github.com/xueromll/sci-etl-core/actions/workflows/ci.yml)
[![Docs](https://github.com/xueromll/sci-etl-core/actions/workflows/docs.yml/badge.svg)](https://xueromll.github.io/sci-etl-core/)
[![PyPI](https://img.shields.io/pypi/v/sci-etl-core)](https://pypi.org/project/sci-etl-core/)

`sci-etl-core` is a Python library for turning scientific papers from any field
into structured, searchable data. It fetches papers from arXiv, PubMed,
OpenAlex, and Semantic Scholar, reads their full text, extracts the values you
ask for with an LLM, and keeps the papers searchable on your own machine.

[udg-catalogue](https://github.com/xueromll/udg-catalogue) shows the result. It
screens astrophysics papers on arXiv, extracts measurements of ultra-diffuse
galaxies, and publishes a cross-matched catalog of 1,927 objects, with keyword
and semantic search over the papers behind it. `sci-etl-core` supplies the
fetching, parsing, extraction, caching, resumable state, and search, while
udg-catalogue adds the astronomy: prompts, validation rules, sky-position
matching, and the dashboard.

Nothing in the library is tied to astronomy. Field knowledge lives in your
prompts, validators, and normalizers, so the same building blocks work for any
field of science.

**Documentation: https://xueromll.github.io/sci-etl-core/**

## Motivation

I built `sci-etl-core` while working with scientific papers during my
undergraduate physics studies, after rewriting the same fetch–parse–extract–cache
machinery one too many times. It's a personal research and learning project,
released free and open-source under the MIT License — not a commercial product.

## Features

- **Composable building blocks** — extractors, parsers, LLM clients, embedding
  memory, processors, exporters, and state managers behind abstract base
  classes. Run the whole pipeline, or use only the parts you need, such as
  search.
- **Async-first orchestration** through `AsyncETLPipeline`, with bounded
  concurrency, resumable crash-safe state, graceful shutdown, polite retries
  that honor `Retry-After`, shared and per-host rate limits, progress events
  and run metrics, and explicit failure signaling through `PipelineAborted`.
  `ETLPipeline` runs the same pipeline from blocking code.
- **Typed extraction** — describe an entity with a Pydantic model, and the
  extractor requests JSON-schema structured output where the provider supports
  it, validates every entity, and records why it rejected one.
- **Claims and provenance** — each extracted value can carry its paper, the
  sentence it was read from, and the model, prompt, and schema that produced
  it, in a claim store you can query and update record by record.
- **LLM response caching** in memory or SQLite, so a rerun doesn't pay for the
  same prompt twice.
- **Semantic memory and local search** — embed full texts into a vector store,
  query a SQLite FTS5 index with Boolean syntax, fuse BM25 with embedding
  similarity, filter by metadata facets, and grow graphs of related papers.
- **Concrete implementations included** — arXiv, PubMed, Semantic Scholar,
  and OpenAlex extractors; OpenAI-compatible chat and embedding clients; PDF,
  LaTeX, HTML, DOCX, and JATS XML parsers; CSV and JSON Lines exporters; SQL
  and Plotly table sinks; dataframe processors and record validators.
- **Typed configuration** from YAML and environment variables, an offline test
  suite at 100% coverage, and PEP 561 type information.
  
## Installation

Python 3.11 or newer is required.

```bash
pip install "sci-etl-core[async,arxiv,llm,pdf]"   # everything the example below uses
pip install "sci-etl-core[full]"                  # every bundled component except local embeddings
```

With Poetry or uv:

```bash
poetry add "sci-etl-core[async,arxiv,llm,pdf]"
uv add "sci-etl-core[async,arxiv,llm,pdf]"
```

The base install requires only Pydantic. It covers both pipelines, the
component contracts, the configuration models, state, the LLM response caches,
the CSV and JSON Lines exporters, claims and provenance, record validators,
LaTeX parsing, and Boolean search. A component that needs another package
imports it when you import the component, so add an extra for each component
group you use:

| Extra | Needed for |
|-------|------------|
| `config` | `load_config` and `load_config_async`, which read YAML and `.env` files |
| `async` | The bundled extractors, `build_async_client` |
| `arxiv` | `AsyncArxivExtractor`, together with `async` |
| `xml` | `JatsXmlParser`, `DocxParser`, and `AsyncPubMedExtractor`, together with `async` |
| `html` | `HtmlTextParser`, which the entity extractor uses for full text that starts with markup |
| `processors` | The pandas processors and table sinks |
| `llm` | `AsyncOpenAICompatibleClient`, token-based truncation |
| `pdf` | `PdfPlumberParser` |
| `sql` | `SqlTableSink`, together with `processors` |
| `viz` | `Plotly3DSink`, together with `processors` |
| `cluster` | `ClusteringStep`, together with `processors` |
| `embeddings` | `AsyncOpenAIEmbedder`, the vector stores, `AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `AsyncSentenceTransformerEmbedder` |

The
[installation guide](https://xueromll.github.io/sci-etl-core/latest/getting-started/installation/)
lists the packages each extra adds.

Prefer configuration to code? [sci-etl-cli](https://github.com/xueromll/sci-etl-cli)
runs these pipelines from a single YAML file.

## Example

```python
import asyncio
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

RELEVANCE_PROMPT = 'Does the paper report measurements of galaxies? Reply with JSON: {"relevant": true} or {"relevant": false}.'
EXTRACTION_PROMPT = 'Extract every measured object. Reply with JSON: {"items": [{"name": "...", "value_a": 0.0}]}.'


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(api_key=os.environ["LLM_API_KEY"], base_url="https://api.openai.com/v1", model="gpt-4o-mini")
    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(client=client, pdf_parser=PdfPlumberParser(), latex_parser=LatexTarballParser()),
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
        exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a"]),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        closeables=[client, llm],
    )
    async with pipeline:
        processed = await pipeline.run(query="all:galaxy", total_limit=50)
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

`results.csv` gets one row per extracted value, tagged with the arXiv id of
the paper it came from, so two papers that disagree about an object give two
rows. The [quick start](https://xueromll.github.io/sci-etl-core/latest/getting-started/quick-start/)
explains what a run does, how it resumes, and what the prompts must ask for.

## Configuration

Settings load from a YAML file into Pydantic models, and the LLM API key comes
from the `LLM_API_KEY` environment variable. Pass `load_env=True` to read a
`.env` file into the environment first. Validation errors raise
`ConfigurationError`, naming each failing key without echoing its value.

```yaml
llm:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
http:
  user_agent: "my-project/1.0 (mailto:you@example.org)"
pipeline:
  search_query: "all:galaxy"
  total_limit: 50
  max_concurrency: 4
  newest_first: true
```

```python
from pathlib import Path

from sci_etl_core import AsyncOpenAICompatibleClient, BaseAppConfig, load_config


class ProjectConfig(BaseAppConfig):
    output_csv: str = "results.csv"


config = load_config(ProjectConfig, Path("config.yaml"), load_env=True)
llm = AsyncOpenAICompatibleClient.from_config(config.llm)
run_arguments = config.pipeline.run_arguments()
```

Subclass `BaseAppConfig` to add typed sections of your own. `from_config`
builders take the matching section, and `run_arguments()` returns the keyword
arguments for `run()`. The
[configuration guide](https://xueromll.github.io/sci-etl-core/latest/getting-started/configuration/)
lists every key and its default.

## Architecture

```mermaid
flowchart LR
    Source[(Literature source)] --> Extractor[AsyncExtractor]
    Extractor -->|listing page| Relevance[AsyncRelevanceFilter]
    Relevance -->|irrelevant| State[(AsyncStateManager)]
    Relevance -->|relevant| FullText[fetch_full_text]
    FullText --> Memory[MemoryIngestor]
    FullText --> Entities[AsyncEntityExtractor]
    Memory --> Vectors[(Vector memory)]
    Memory --> Index[(Text index)]
    Entities --> Exporter[AsyncExporter]
    Exporter --> State
    Relevance -.-> LLM[AsyncLLMClient]
    Entities -.-> LLM
    Vectors --> Search[AsyncHybridSearcher]
    Index --> Search
```

`AsyncETLPipeline` receives every collaborator through its constructor and
depends only on the abstract interfaces, so any stage can be replaced by
another implementation or a test double. It pages through the listing by
cursor, processes up to `max_concurrency` records at a time, and marks a record
processed only once the exporter holds its entities durably, so a failed
record is retried on the next run, until it has failed in `max_attempts` runs. The
[architecture guide](https://xueromll.github.io/sci-etl-core/latest/guide/architecture/)
describes each layer.

## Documentation

| Topic | Where |
|-------|-------|
| Installation, quick start, blocking usage, configuration | [Getting started](https://xueromll.github.io/sci-etl-core/latest/getting-started/installation/) |
| Cases the library doesn't fit | [When not to use it](https://xueromll.github.io/sci-etl-core/latest/getting-started/when-not-to-use/) |
| Sources, post-processing, semantic memory, state, shutdown, retries, rate limiting, events, caching | [Guide](https://xueromll.github.io/sci-etl-core/latest/guide/sources/) |
| Boolean and hybrid search, facets, discovery graphs | [Local search and discovery](https://xueromll.github.io/sci-etl-core/latest/guide/search/) |
| Components and how they connect | [Architecture](https://xueromll.github.io/sci-etl-core/latest/guide/architecture/) |
| Every public class and function | [API reference](https://xueromll.github.io/sci-etl-core/latest/reference/) |
| The `sci-etl` command-line tool | [CLI](https://xueromll.github.io/sci-etl-core/latest/cli/) |

## Testing

```bash
pip install -e ".[full,dev,lint]"
pytest --cov=sci_etl_core --cov-report=term-missing
ruff check .
mypy
```

The suite runs offline, and `pytest --cov` fails if line coverage drops below
100%.

## Contributing

Contributions are welcome — new extractors, parsers, exporters, and embedding
backends especially. See [CONTRIBUTING.md](CONTRIBUTING.md) to get set up, and
browse [good first issues](.github/ISSUE_TEMPLATE/good_first_issue.md) if
you're new. Native speakers can help review the Russian, Spanish, Chinese, and
Arabic documentation; [TRANSLATING.md](TRANSLATING.md) names the owner of each
language and holds the glossary. Moving an existing pipeline onto the library? Follow
[Migrating a pipeline](https://xueromll.github.io/sci-etl-core/latest/guide/migrating-a-pipeline/).
Upgrading to a new release? See [MIGRATION.md](MIGRATION.md).
What's planned is in [ROADMAP.md](ROADMAP.md), and releases are recorded in
[CHANGELOG.md](CHANGELOG.md). All participation is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

This is a non-commercial research and educational project, freely available under the MIT License. See [LICENSE](LICENSE) for details.
