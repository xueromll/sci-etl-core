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

Linting and type checking aren't configured in the repository yet. If you use
them, run with defaults and keep unrelated reformatting out of your PR:

```bash
pip install ruff mypy
ruff check .
ruff format --check .
mypy src/sci_etl_core
```

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
   - `README.md` for usage
   - `MIGRATION.md` for breaking changes
   - `ROADMAP.md` when you ship a listed item
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
| Processor | `Processor` | `process(frame) -> DataFrame` | Don't mutate the input frame. |
| Validator | `RecordValidator` | `is_valid(record) -> bool` | Operates on one entity dict. |

Register the new class in its subpackage's `_EXPORTS` map and `TYPE_CHECKING`
imports. If it's a primary user-facing class, add it to
`sci_etl_core/__init__.py` the same way. Add a case for it to
`tests/contract/test_abc_conformance.py`.

Happy hacking — and thank you for contributing!
