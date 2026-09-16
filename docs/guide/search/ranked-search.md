# Ranked search and filtering

The stores take parsed queries, and `AsyncHybridSearcher` takes text and parses
it once, before any I/O. A ranked search needs a term to rank by, so a query
whose every term is negated, such as `NOT simulation` or
`NOT simulation OR quasar`, raises `SearchQueryError` from `search`. Ask
`filter_ids` instead. It accepts any query and returns a `frozenset` of record
ids, which carries no order and so can't be mistaken for a ranking:

```python
from sci_etl_core.search import parse_query

hits = await text_store.search(parse_query("photometr* dwarf"), limit=20)
observational = await text_store.filter_ids(parse_query("NOT simulation"))
```

A `TextHit` has a `score` where higher is better. Its scale depends on the
corpus, so compare scores only within one result list. Its `snippet` is plain
text from one field, and `highlights` holds `[start, end)` character offsets
into it for the matched words, so the UI applies its own markup.
