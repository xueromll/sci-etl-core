# Store ownership

Three facts make it matter who closes a store:

- `aclose()` on a SQLite store isn't final: a later call reopens the
  connection.
- `async with pipeline` closes every entry in `closeables` each time the block
  exits.
- A store's lock belongs to the first event loop that contends for it. Using
  the same instance from a second loop fails, but only when both use it at
  once, so a quiet test passes and a busy UI breaks.

So give every store instance exactly **one owner**, the scope that outlives
all its users, and let only the owner call `aclose()`. Use each instance from
**one event loop**. Everything else borrows: `AsyncHybridSearcher`, the edge
sources, and `AsyncCompositeIngestor` never close a store.

| Deployment | Owner of the SQLite stores | Pipeline `closeables` |
|------------|----------------------------|-----------------------|
| Pipeline and UI in separate processes | each process, for the instances it opened on the shared files | lists the pipeline's own instances |
| One-shot script that ingests and queries inside `async with pipeline` | the pipeline | lists the stores; queries run inside the block |
| Long-lived application on one event loop that starts ingest runs | the application, which closes them on shutdown | must **not** list them, or the end of each run closes them and the next query reopens an unowned connection |
| Blocking `ETLPipeline` plus an application on its own loop | two sets of instances on the same files: one used by the pipeline's background loop, one by the application's loop | lists the pipeline's set |

SQLite's WAL mode lets one process read while another writes.
