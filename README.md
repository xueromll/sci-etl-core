# sci-etl-core

[![CI](https://github.com/xueromll/sci-etl-core/actions/workflows/ci.yml/badge.svg)](https://github.com/xueromll/sci-etl-core/actions/workflows/ci.yml)
[![Docs](https://github.com/xueromll/sci-etl-core/actions/workflows/docs.yml/badge.svg)](https://xueromll.github.io/sci-etl-core/)
[![PyPI](https://img.shields.io/pypi/v/sci-etl-core)](https://pypi.org/project/sci-etl-core/)

A reusable, **domain-agnostic** Python library for scientific text mining and
ETL. `sci-etl-core` gives you composable building blocks — extractors, parsers,
LLM clients, embedding memory, processors, exporters, and state managers —
behind abstract base classes, so you can assemble a pipeline for *any* corpus
without inheriting constants tied to a specific field of science.

The library is **async-first**. Every component is an `async` implementation,
orchestrated by `AsyncETLPipeline`. For scripts that don't want to manage an
event loop, `ETLPipeline` is a single blocking entrypoint that runs the same
pipeline on a background loop.

**Documentation: https://xueromll.github.io/sci-etl-core/**

## Features

- **Pluggable async interfaces** for every stage, with `Sync*Adapter` wrappers
  for existing blocking implementations.
- **Built-in orchestration** with bounded concurrency, resumable crash-safe
  state, polite retries that honor `Retry-After`, and explicit failure
  signaling through `PipelineAborted`.
- **Semantic memory and local search** — embed full texts into a vector store,
  query a SQLite FTS5 index with Boolean syntax, fuse BM25 with embedding
  similarity, filter by metadata facets, and grow graphs of related papers.
- **Concrete implementations included** — arXiv extractor; OpenAI-compatible
  chat and embedding clients; PDF, LaTeX, and HTML parsers; CSV, SQL, and
  Plotly exporters; dataframe processors and record validators.
- **Typed configuration** from YAML and `.env`, an offline test suite at 100%
  coverage, and PEP 561 type information.

## Installation

Python 3.10 or newer is required.

```bash
pip install "sci-etl-core[async,llm,pdf]"   # everything the example below uses
pip install "sci-etl-core[full]"            # every bundled component except local embeddings
```

Components load their optional dependencies only when you import them. The
[installation guide](https://xueromll.github.io/sci-etl-core/latest/getting-started/installation/)
lists what each extra adds.

Prefer configuration to code? [sci-etl-cli](https://github.com/xueromll/sci-etl-cli)
runs these pipelines from a single YAML file.

## Example

```python
import asyncio
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvUpsertExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.processors import DefaultKeyNormalizer

RELEVANCE_PROMPT = 'Does the paper report measurements of galaxies? Reply with JSON: {"relevant": true} or {"relevant": false}.'
EXTRACTION_PROMPT = 'Extract every measured object. Reply with JSON: {"items": [{"name": "...", "value_a": 0.0}]}.'


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(api_key=os.environ["LLM_API_KEY"], base_url="https://api.openai.com/v1", model="gpt-4o-mini")
    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(client=client, pdf_parser=PdfPlumberParser(), latex_parser=LatexTarballParser()),
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
        exporter=AsyncCsvUpsertExporter(key_column="name", value_columns=["value_a"], normalizer=DefaultKeyNormalizer()),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        destination="results.csv",
        closeables=[client, llm],
    )
    async with pipeline:
        processed = await pipeline.run(query="all:galaxy", total_limit=50)
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

The [quick start](https://xueromll.github.io/sci-etl-core/latest/getting-started/quick-start/)
explains what a run does, how it resumes, and what the prompts must ask for.

## Documentation

| Topic | Where |
|-------|-------|
| Installation, quick start, blocking usage, configuration | [Getting started](https://xueromll.github.io/sci-etl-core/latest/getting-started/installation/) |
| Post-processing, semantic memory, state, retries, rate limiting | [Guide](https://xueromll.github.io/sci-etl-core/latest/guide/sources/) |
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
you're new. Moving an existing pipeline onto the library? See [MIGRATION.md](MIGRATION.md).
What's planned is in [ROADMAP.md](ROADMAP.md), and releases are recorded in
[CHANGELOG.md](CHANGELOG.md). All participation is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

Released under the MIT License. See [LICENSE](LICENSE) for details.
