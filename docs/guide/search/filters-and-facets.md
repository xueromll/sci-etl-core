# Filters and facets

Metadata filters are `MetadataFilter` and `RangeFilter` values passed beside
the query, never written into it. A store tags each document under the
metadata keys named in its `facet_keys`. Every bundled extractor fills
`categories` and `authors` in `RawRecord.metadata`, and `published` and `year`
when the source has a date (see [Supported sources](../sources.md) for the keys
each source adds), and `AsyncSearchIndexer` copies that metadata into the
index.

```python
from sci_etl_core.search import MetadataFilter, RangeFilter, parse_query

filters = (
    MetadataFilter("categories", {"astro-ph.GA", "astro-ph.CO"}),
    RangeFilter("published", low="2020-01", high="2024-06"),
)
outcome = await searcher.search("dwarf galaxy", filters=filters)
facets = await text_store.facet_counts(["categories", "year"], query=parse_query("dwarf galaxy"), filters=filters)
```

- **Matching.** A `MetadataFilter` keeps the records tagged with any of its
  values, and with `negated=True` drops them. Every filter must pass. Several
  values of one key go in one filter: two filters on the same key, including a
  `MetadataFilter` and a `RangeFilter`, or a key outside `facet_keys`, raise
  `ValueError` before any I/O.
- **Tags.** Strings, integers, and lists of them become tags; other values are
  not tagged. A record with several tags under a key, such as several
  authors, passes a filter when any one of them does.
- **Before the limit.** Filters are applied inside the index, before `limit`,
  and to both legs of a hybrid search, so a filtered-out record never takes a
  result slot. `filter_graph` applies them to a discovery graph the same way.
- **Facet counts.** `facet_counts` maps each key to `(value, count)` pairs,
  sorted by count and then value, without zero counts. Each key's counts apply
  the query and every filter on *other* keys, so a count says how many results
  selecting that value would give, and the other values of a filtered key stay
  visible. `query=None` counts across the whole index.
- **Changing `facet_keys`.** The keys are fixed when a store is constructed
  and recorded in the file. To change them, construct the store with the new
  keys and `await text_store.rebuild_tags()`. Until then, a filter or facet on
  a key whose tags aren't built raises `SearchStoreError`.

## Ranges

A `RangeFilter` keeps the records with a tag between `low` and `high`. Both
bounds are inclusive, either can be left out, and `negated=True` drops the
records in range instead. The type of the bounds decides how tags compare:

| Bounds | Compares | Example | Keeps |
|--------|----------|---------|-------|
| Integers | as numbers | `RangeFilter("year", 2020, 2024)` | the tags `2020` to `2024`, stored as integers or as text |
| Text | as text, with `high` against as many leading characters | `RangeFilter("published", "2024-01", "2024-06")` | `2024-01-01` up to `2024-06-30T23:59:59Z` |

- **Integers.** Only a tag written the way Python writes an integer can be in
  an integer range: `2024`, `0`, and `-3` can, while `"07"`, `"+3"`, and
  `"2024-05-01"` never are. Integer bounds suit counts, such as citations,
  that text comparison would order wrongly.
- **Text.** Text compares character by character, so ISO 8601 dates and
  four-digit years order correctly. Because `high` is compared with the
  tag's first characters, `high="2024-06"` keeps every date in June 2024, and
  `high="2024"` keeps every date in 2024.
- **Invalid ranges.** A range with no bound, an empty text bound, a `bool` or
  `float` bound, one integer and one text bound, or a `low` above `high`, so
  that nothing could match, raises when it is constructed.

## Counting ranges

`range_counts` counts the matching records in each range, for histogram
buckets or presets such as "last 5 years". Like `facet_counts`, each count
applies the query and every filter on *other* keys, so selecting a bucket
leaves the counts of the other buckets visible:

```python
from sci_etl_core.search import RangeFilter, parse_query

buckets = [RangeFilter("year", low, low + 4) for low in range(2000, 2025, 5)]
counts = await text_store.range_counts(buckets, query=parse_query("dwarf galaxy"), filters=filters)
for bucket, count in zip(buckets, counts):
    print(f"{bucket.low}–{bucket.high}: {count}")
```

The counts come back as a tuple in the order of `ranges`, and ranges may share
a key and overlap. `AsyncSqliteFts5Store` counts every range in one consistent
read. A custom store inherits a version that calls `filter_ids` once per range.
