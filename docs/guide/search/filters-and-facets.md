# Filters and facets

Metadata filters are `MetadataFilter` values passed beside the query, never
written into it. A store tags each document under the metadata keys named in
its `facet_keys`. `AsyncArxivExtractor` fills `categories`, `authors`,
`published`, and `year` in `RawRecord.metadata`, and `AsyncSearchIndexer`
copies that metadata into the index.

```python
from sci_etl_core.search import MetadataFilter, parse_query

filters = (
    MetadataFilter("categories", {"astro-ph.GA", "astro-ph.CO"}),
    MetadataFilter("year", {"2020", "2021"}, negated=True),
)
outcome = await searcher.search("dwarf galaxy", filters=filters)
facets = await text_store.facet_counts(["categories", "year"], query=parse_query("dwarf galaxy"), filters=filters)
```

- **Matching.** A filter keeps the records tagged with any of its values, and
  with `negated=True` drops them. Every filter must pass. Several values of one
  key go in one filter: two filters on the same key, or a key outside
  `facet_keys`, raise `ValueError` before any I/O.
- **Tags.** Strings, integers, and lists of them become tags; other values are
  not tagged. Matching is exact, so there are no range filters over dates or
  years.
- **Before the limit.** Filters are applied inside the index, before `limit`,
  and to both legs of a hybrid search, so a filtered-out record never takes a
  result slot.
- **Facet counts.** `facet_counts` maps each key to `(value, count)` pairs,
  sorted by count and then value, without zero counts. Each key's counts apply
  the query and every filter on *other* keys, so a count says how many results
  selecting that value would give, and the other values of a filtered key stay
  visible. `query=None` counts across the whole index.
- **Changing `facet_keys`.** The keys are fixed when a store is constructed
  and recorded in the file. To change them, construct the store with the new
  keys and `await text_store.rebuild_tags()`. Until then, a filter or facet on
  a key whose tags aren't built raises `SearchStoreError`.
