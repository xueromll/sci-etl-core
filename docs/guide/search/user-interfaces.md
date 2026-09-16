# Building a user interface

`sci_etl_core.discovery` holds the read-model a presentation layer renders:
`DiscoveryResult` (the query text and chips, fused hits, graph, facets,
matched count, elapsed time, and degraded and skipped legs) and `Facet`. Both
are frozen dataclasses, and importing the module loads no store, no event-loop
machinery, and no optional dependency.

Keep parsing on the keystroke and make only retrieval asynchronous: debounce
it, cancel a search when a newer one starts, and drop any result that arrives
after a newer search began.

Before sharing stores between a UI and ingest runs, read
[Store ownership](store-ownership.md).
