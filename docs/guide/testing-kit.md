# Testing your components

`sci_etl_core.testing` holds contract suites: pytest test classes that check
a component's behavior against the contract of its base class. Subclass the
suite for your component, add a fixture that builds it, and pytest runs every
test of the suite against your implementation. The bundled implementations
run the same suites.

| Suite | Checks | Bundled implementations it runs against |
|-------|--------|-----------------------------------------|
| `ExtractorContract` | `AsyncExtractor` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor` |
| `StateManagerContract` | `AsyncStateManager` | `AsyncFileStateManager`, `AsyncSqliteStateManager` |
| `ExporterContract` | `AsyncExporter` | `AsyncJsonlExporter`, `AsyncCsvExporter`, `AsyncClaimStoreExporter` |
| `EmbeddingStoreContract` | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`, `AsyncSqliteEmbeddingStore` |

## Installing {#installing}

The suites need pytest, which the `testing` extra installs:

```bash
pip install "sci-etl-core[testing]"
```

No other module of the library imports pytest. The tests are plain functions
that run each scenario with `asyncio.run`, so pytest-asyncio is not needed.

## Writing a contract test {#writing-a-contract-test}

Subclass the suite in a test module, under a name pytest collects, and give
it the fixture the suite asks for. Here a state manager that keeps its state
in memory runs `StateManagerContract`:

```python
import dataclasses

import pytest

from sci_etl_core import AsyncStateManager, PipelineMetadata
from sci_etl_core.testing import StateManagerContract


class MemoryStateManager(AsyncStateManager):
    def __init__(self) -> None:
        self._processed: set[str] = set()
        self._metadata = PipelineMetadata()

    async def load_processed_ids(self) -> set[str]:
        return set(self._processed)

    async def mark_processed(self, record_id: str) -> None:
        self._processed.add(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return dataclasses.replace(self._metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        self._metadata = dataclasses.replace(metadata)


class TestMemoryStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self):
        manager = MemoryStateManager()
        return lambda: manager
```

`python -m pytest` now runs every test of the suite against
`MemoryStateManager`. The suite class itself is not collected, because its
name does not start with `Test`.

The fixture returns a factory: a callable that takes no argument and returns
a new instance over the same storage each time, as each run of a pipeline
opens it. The suite calls it more than once in a test to check that what one
instance saved, the next one loads. A component that keeps its state in
memory, like the one above, returns the same instance every time. Storage
starts empty in every test, so build it from `tmp_path` or inside the
fixture. The suite calls the factory inside a running event loop, and ends
each instance as a run ends: a state manager is flushed, then closed with
`aclose()` when it has one, and an exporter or a vector store is closed.

## Fixtures {#fixtures}

| Suite | Required fixtures | Optional fixtures |
|-------|-------------------|-------------------|
| `ExtractorContract` | `make_extractor` | `make_unavailable_extractor` |
| `StateManagerContract` | `make_state_manager` | `write_newer_schema` |
| `ExporterContract` | `make_exporter`, `read_exported` | `make_entities`, `write_newer_schema` |
| `EmbeddingStoreContract` | `make_store` | `write_newer_schema` |

- **`make_extractor`, `make_state_manager`, `make_exporter`, and
  `make_store`** return the factory described above.
- **`read_exported`** returns an async callable that takes a record id and
  returns the entities the destination holds for that record, or an empty
  sequence. The suite compares two reads, so return a form that compares
  equal when the content is the same.
- **`make_entities`** returns a callable that builds `count` distinct
  entities for a record. The default builds dicts with a `name` and a `value`
  key; override it when your exporter takes other entities, such as claims.
- **`write_newer_schema`** returns a callable that writes, into the storage
  the factory opens, a file or database from a newer schema version than your
  component supports. The suite calls it before it creates an instance and
  expects a `SciEtlError`. The default returns `None`.
- **`make_unavailable_extractor`** returns a factory for an extractor whose
  source answers every request with a server-side failure, such as status
  `503`, without waiting between retries. The suite expects `UpstreamError`
  rather than an empty page. The default returns `None`.

The same state manager suite, run against the bundled SQLite state manager,
also checks that a database from a newer release is refused:

```python
import sqlite3
from contextlib import closing

import pytest

from sci_etl_core import AsyncSqliteStateManager
from sci_etl_core.testing import StateManagerContract


class TestSqliteStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: AsyncSqliteStateManager(tmp_path / "state.db")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        def write():
            with closing(sqlite3.connect(tmp_path / "state.db")) as connection:
                connection.execute("PRAGMA user_version = 99")

        return write
```

An exporter also needs `read_exported`, which reads its destination back:

```python
import pytest

from sci_etl_core.exporters import AsyncJsonlExporter, read_jsonl_export
from sci_etl_core.testing import ExporterContract


class TestJsonlExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncJsonlExporter(tmp_path / "out.jsonl", fsync=False)

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            return read_jsonl_export(tmp_path / "out.jsonl").get(record_id, [])

        return read
```

## Testing an extractor offline {#testing-an-extractor-offline}

The extractor suite never calls the network. Serve the listing from a stub,
such as an `httpx.AsyncClient` built on `httpx.MockTransport`, and make it
answer the same request the same way every time. The listing must hold at
least two pages for the suite's query and end within `max_pages` pages. Set
these class attributes on your subclass to fit your source:

| Attribute | Default | Meaning |
|-----------|---------|---------|
| `query` | `"contract"` | The query every test lists |
| `page_size` | `2` | The page size every test asks for |
| `max_pages` | `50` | The most pages the listing may take to end |

## Optional capabilities and skips {#optional-capabilities-and-skips}

A test that checks an optional capability is skipped, with the reason, when
your component lacks it:

- **State managers:** failed attempts, when `record_failure` keeps the
  default that tracks nothing; `forget`, when the state manager is not
  `Forgetting`; reuse after `aclose()`, when it has no `aclose`.
- **Exporters:** reading a write before `flush`, when `durable_writes` is
  `False`.
- **Vector stores:** `iter_records`, when the store keeps the default that
  raises `NotImplementedError`.
- **Extractors:** the offset test, when the extractor is not an
  `OffsetListing`; the unavailable-source test, when
  `make_unavailable_extractor` returns `None`.
- **State managers, exporters, and vector stores:** the schema-version test,
  when `write_newer_schema` returns `None`.

## What the suites check {#what-the-suites-check}

- **`ExtractorContract`:** the first page is a well-formed `ListingPage` with
  records and a next cursor; a next cursor returns the same page again and
  from a new extractor, as a resumed run asks for it; following next cursors
  ends the listing, and a truncated page has no next cursor; for an
  `OffsetListing`, offset 0 is the first page and the first page's entry count
  is the second page's offset; `fetch_full_text` returns a string; an
  unreachable source raises `UpstreamError`.
- **`StateManagerContract`:** new storage is empty; processed ids, saved
  metadata, and failed attempts persist to the next instance; concurrent
  marks are all kept; `save_metadata` stamps the run time; `mark_processed`
  clears a record's attempts; `forget` clears marks and attempts and keeps the
  cursor; state from a newer schema version is refused; a state manager works
  again after `aclose()`.
- **`ExporterContract`:** a run exports every record's entities; repeating a
  write, concurrently, in the same run, or in a later run, leaves what one
  write left; a record written with no entities holds none; a run without
  writes succeeds; an exporter runs again after `aclose()`; with
  `durable_writes = True`, a write is readable before `flush`; a destination
  from a newer schema version is refused.
- **`EmbeddingStoreContract`:** a new store is empty; a chunk added again
  under its record id and index replaces the old one; chunks persist to the
  next instance; hits come best first by cosine similarity and honor `top_k`,
  `min_score`, and `exclude_record_id`; a vector holding NaN never matches;
  `delete_record` and `replace_record` leave none of a record's old chunks;
  `iter_records` yields passages in order; a store works again after
  `aclose()`; storage from a newer schema version is refused.

The suites check behavior through the public methods only. The
[contract table](../project/contributing.md#adding-a-new-component) lists what
each component must do, and the [testing API reference](../reference/testing.md)
documents every suite.
