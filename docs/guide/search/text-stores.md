# Text stores

- **`InMemoryTextSearchStore(facet_keys=...)`** suits tests and short-lived
  runs. It matches exactly the records the SQLite store matches and scores
  with the same BM25 formula.
- **`AsyncSqliteFts5Store(path, facet_keys=..., weights=...)`** persists the
  index. Each article's text is stored once, each write is one transaction,
  and every SQLite failure, including a file that isn't a database, raises
  `SearchStoreError`. `weights=BM25Weights(title=10.0, abstract=4.0, body=1.0)`
  sets how much a match in each field counts; those are the defaults.
- **FTS5 is required.** The store needs a Python whose SQLite was built with
  FTS5, and raises `SearchStoreError` when it is constructed otherwise.
  `fts5_available()` checks in advance; `InMemoryTextSearchStore` works
  everywhere.
- **Maintenance is explicit.** `optimize()` merges the index's segments.
  `integrity_check()` returns `False` when the index disagrees with the stored
  documents, for example after the file was edited by other tools, and
  `rebuild_index()` repairs it from the stored text without fetching anything.
  A file created by a newer version of the library raises `SearchStoreError`
  rather than being used.
- **Custom stores** subclass `AsyncTextSearchStore`; see
  [Adding a new component](../../project/contributing.md#adding-a-new-component).
