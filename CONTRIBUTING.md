# Contributing to sci-etl-core

Thanks for your interest in improving `sci-etl-core`! New extractors, parsers,
exporters, embedding backends, and documentation fixes are all genuinely
welcome — first-time contributors included. This guide gets you productive
quickly.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development Setup

```bash
git clone https://github.com/xueromll/sci-etl-core.git
cd sci-etl-core

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[full,dev]"
```

- **Python 3.10+** is required; the codebase uses `X | Y` unions and
  `slots=True` dataclasses.
- **Why `[full]`:** the suite exercises every bundled component.
- **Not needed for tests:** `sentence-transformers` and a real SQL driver are
  mocked or stubbed.

## How the Codebase Works — Read This First

- **Async is the only implementation.** Every component is `async`. Don't add
  synchronous twins of components; there is no code generator. Blocking
  implementations reach a pipeline through the adapters in `_adapters.py`.
- **One blocking entrypoint.** `ETLPipeline` (`pipeline.py`) runs
  `AsyncETLPipeline` through `_sync_bridge.run_sync`. Discuss new blocking APIs
  in an issue first.
- **Keep the event loop free.** Run CPU-bound or blocking work with
  `asyncio.to_thread`. Parsers, pandas, `sqlite3`, and file IO all follow this
  pattern.
- **Inject collaborators.** Clients, parsers, `sleep`, and `logger` are
  constructor arguments so tests can substitute them. Accept
  `logger: Callable[[str], None] | None` and an injectable `sleep` wherever
  timing or retries are involved.
- **Never swallow cancellation.** Before catching broad exceptions, catch and
  re-raise `asyncio.CancelledError` (see `llm/relevance_async.py`).
- **Signal failures with exceptions.** Use the hierarchy in `exceptions.py`.
  Don't return `None` or an empty result for a transport failure — the pipeline
  relies on `UpstreamError` and `MalformedResponseError` to tell faults apart
  from the end of the data.
- **Be safe under concurrency.** The pipeline calls relevance filters, entity
  extractors, `export`, and `mark_processed` concurrently. Serialize shared
  writes with an `asyncio.Lock`, and write files with
  `_atomic_io.atomic_write_text`. `AsyncCsvUpsertExporter` and
  `AsyncFileStateManager` are good models.
- **Keep optional imports lazy.** Each package `__init__.py` maps public names
  to their modules in `_EXPORTS` and loads them on first access, so importing
  one component never requires another's optional dependencies. Register new
  public names there and in the matching `TYPE_CHECKING` imports (a test checks
  that they agree), and add any new third-party dependency to an extra in
  `pyproject.toml`.
- **No domain-specific constants** in the core; keep it field-agnostic.

## Running Tests

The suite is offline — no network, live LLM, or embedding service required.

```bash
pytest                                                # everything
pytest tests/async                                    # async components
pytest tests/contract                                 # ABC conformance
pytest --cov=sci_etl_core --cov-report=term-missing   # coverage report
```

- **Coverage stays at 100%.** `pytest --cov=sci_etl_core` fails below 100%
  (configured in `pyproject.toml`), so new and changed code needs tests that
  cover it. Use `# pragma: no cover` only for lines that can't run on the test
  platform, such as OS-specific imports.
- **Async tests** use an explicit `@pytest.mark.asyncio` marker (auto mode
  isn't configured), with `AsyncMock` or the `mocker` fixture.
- **No real network or backoff waits.** Mock HTTP, LLM, and embedding clients,
  and inject `sleep=AsyncMock()` to skip backoff delays.
- **Contract tests.** Every public ABC implementation has a case in
  `tests/contract/test_abc_conformance.py`; add one for each new
  implementation.
- **Property tests.** Put invariants — especially ones two backends must share,
  such as the in-memory and SQLite embedding stores — in Hypothesis tests in
  `tests/test_properties.py`.

## Code Style

- **PEP 8** naming: `snake_case` functions and variables, `CapWords` classes,
  `UPPER_CASE` constants.
- **Type hints on every public signature.** The package ships `py.typed`;
  keep it accurate.
- **Small, single-responsibility functions.** Prefer composition and dependency
  injection over branching on hard-coded logic.
- **Docstrings for contracts and intent.** Document `Raises:` and non-obvious
  decisions; don't write comments that restate the code.
- **American English** for identifiers and docstrings.

ruff and mypy run in CI on every push and pull request, configured in
`pyproject.toml`. Run both before opening a PR:

```bash
pip install -e ".[full,dev,lint]"
ruff check .
mypy
```

`ruff check --fix .` sorts imports and applies the other safe fixes.
Formatting isn't enforced, so keep unrelated reformatting out of your PR.
Record user-facing changes under the unreleased version in
[CHANGELOG.md](CHANGELOG.md).

## Documentation

The documentation site is built with [MkDocs](https://www.mkdocs.org/) and
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) from
`mkdocs.yml` and the `docs/` folder, and published to GitHub Pages.

```bash
pip install -e ".[docs]"
git clone https://github.com/xueromll/sci-etl-cli.git ../sci-etl-cli
pip install --no-deps -e ../sci-etl-cli
mkdocs serve                                          # preview at http://127.0.0.1:8000
mkdocs build --strict                                 # the check CI runs
```

- **Where pages live.** Guides are Markdown files under `docs/`, listed in the
  `nav` of `mkdocs.yml`. `CHANGELOG.md`, `MIGRATION.md`, `ROADMAP.md`, this
  guide, `SECURITY.md`, and `CODE_OF_CONDUCT.md` stay at the repository root;
  the pages under `docs/project/` render them, and links between them are
  rewritten for the site.
- **The CLI section** comes from the `docs/` folder and `nav` of the
  sci-etl-cli repository. The build looks for a checkout beside this one, or at
  the path in `SCI_ETL_CLI_DIR`; without one it leaves the section out, which
  `--strict` reports as a failure. Change CLI pages in that repository.
- **API reference.** The pages under `docs/reference/` are generated from
  docstrings. A new public module needs a `::: module.path` entry on one of
  them; `tests/test_docs.py` fails until it has one.
- **Code examples.** `tests/test_docs.py` also checks that every Python example
  under `docs/` compiles and that every name it imports from `sci_etl_core`
  exists, so renaming a public name means updating the examples too.
- **Publishing.** The docs workflow deploys `master` as the `dev` version and
  each `v*` tag as its minor version, for example `0.3`, with the `latest`
  alias. Nothing needs to be published by hand.

## Commit Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`. Mark
breaking changes with `!` (e.g. `refactor(core)!: ...`).

Examples:

```
feat(extractors): add PubMed async extractor
fix(exporters): serialize concurrent CSV upserts
docs(readme): document ETLPipeline event-loop behavior
```

Keep the summary imperative and under ~72 characters. Reference issues in the
body (`Closes #123`).

## Pull Request Process

1. **Open an issue first** for anything non-trivial, so we can agree on the
   approach.
2. **Branch** from `master`, e.g. `feat/pubmed-extractor`.
3. **Write tests** alongside your change; keep coverage at 100%.
4. **Run** the test suite locally (plus lint and type checks if you use them).
5. **Update the docs** for user-facing changes:
   - the pages under `docs/` for usage; keep `README.md` a short overview
   - `MIGRATION.md` when the change affects moving an existing pipeline onto
     the library
   - `ROADMAP.md` when you ship a listed item
   - the pull request description for any breaking change, with what users
     need to update
6. **Fill in** the [pull request template](.github/PULL_REQUEST_TEMPLATE.md).
7. **Keep PRs focused** — one logical change per PR is easiest to review.

A maintainer will review promptly. Expect a friendly, constructive exchange;
requested changes are about the code, never about you.

## Adding a New Component

Most contributions plug into an existing abstract base class:

| Component | Subclass | Implement | Contract |
|-----------|----------|-----------|----------|
| Extractor | `AsyncExtractor` | `async search`, `parse_listing` (**synchronous**), `async fetch_full_text` | Raise `UpstreamError` when the source can't be reached after retries, `ExtractionError` when it rejects a request outright, and `MalformedResponseError` for an unreadable listing. Return `([], 0)` only for a genuinely empty listing. Skip ids in `seen_ids`, and skip entries that have no id. |
| Parser | `Parser` (optionally `TableParser`) | `extract_text(content: bytes) -> str` | Synchronous; callers run it in a worker thread. Raise `ParsingError` for bytes it can't read. |
| LLM client | `AsyncLLMClient` | `async complete_json(system_prompt, user_content, timeout)` | Return the parsed JSON object; raise `LLMError` on failure or when the body isn't a JSON object. |
| Relevance filter | `AsyncRelevanceFilter` | `async is_relevant(record)` | Re-raise `CancelledError`. |
| Entity extractor | `AsyncEntityExtractor` | `async extract(text) -> list[dict]` | Each dict becomes one export row. Raise on failure instead of returning `[]`, so the record is retried. |
| Exporter | `AsyncExporter` | `async export(data, destination)` | As a pipeline exporter it receives `list[dict]`, concurrently; serialize writes. |
| State manager | `AsyncStateManager` | `load_processed_ids`, `mark_processed`, `load_metadata`, `save_metadata` | Concurrency-safe. Override `flush()` if you buffer; add `aclose()` if you hold connections. |
| Embedder | `AsyncEmbedder` | `async embed(texts) -> list[list[float]]` | One vector per input, same order; raise `EmbeddingError`. |
| Vector store | `AsyncEmbeddingStore` | `add`, `delete_record`, `query`, `count` | Replace chunks with the same `(record_id, chunk_index)`; `delete_record` removes all of a record's chunks. Override `replace_record` (delete then add by default) if your backend can do both atomically. Never return hits with non-finite scores. Match `InMemoryEmbeddingStore` for `top_k`, `min_score`, and `exclude_record_id`. Serialize use of a shared connection, and raise `EmbeddingStoreError`. |
| Chunker | `TextChunker` | `chunk(text) -> list[str]` | Ordered passages covering the text. |
| Text search store | `AsyncTextSearchStore` | `facet_keys` property, `index`, `delete_record`, `search`, `filter_ids`, `get_documents`, `facet_counts`, `count` | Take parsed queries, never text. Reject a query `search` can't rank with `require_rankable`. Order equal scores by `record_id`, and apply filters before `limit`. Raise `ValueError` before any I/O for a filter or facet key outside `facet_keys` or two filters on one key (`validate_filters`, `validate_facet_keys`). Match `InMemoryTextSearchStore`'s results, and raise `SearchStoreError`. |
| Edge source | `AsyncEdgeSource` | `kind` property, `async neighbours(record_ids, limit)` | Map every requested id, even one with no neighbors, to up to `limit` `(record_id, weight)` pairs, best first, where a higher weight means more related. Never close the stores you were given. |
| Processor | `Processor` | `process(frame) -> DataFrame` | Don't mutate the input frame. |
| Validator | `RecordValidator` | `is_valid(record) -> bool` | Operates on one entity dict. |

Register the new class in its subpackage's `_EXPORTS` map and `TYPE_CHECKING`
imports. A new module also needs an entry on its page under `docs/reference/`. If it's a primary user-facing class, add it to
`sci_etl_core/__init__.py` the same way. Add a case for it to
`tests/contract/test_abc_conformance.py`.

Happy hacking — and thank you for contributing!
