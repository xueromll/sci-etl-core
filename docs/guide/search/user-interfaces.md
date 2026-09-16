# Building a user interface

`sci_etl_core.discovery` holds the read-model a presentation layer renders:
`DiscoveryResult` (the query text and chips, fused hits, graph, facets,
matched count, elapsed time, and degraded and skipped legs) and `Facet`. Both
are frozen dataclasses, and importing the module loads no store, no event-loop
machinery, and no optional dependency.

Render `FusedHit.snippets` with your own markup from their `highlights`, one
line per field, and label a hit whose `lexical_rank` is `None` as a match by
meaning. Build date or year histograms from `range_counts`, which leaves every
bucket visible while one is selected.

Keep parsing on the keystroke and make only retrieval asynchronous: debounce
it, cancel a search when a newer one starts, and drop any result that arrives
after a newer search began.

Before sharing stores between a UI and ingest runs, read
[Store ownership](store-ownership.md).
