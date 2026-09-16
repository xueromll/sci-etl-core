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
corpus, so compare scores only within one result list.

## Snippets

A hit's `snippet` is plain text from the field that matched best, and
`highlights` holds `[start, end)` character offsets into it for the matched
words, so the UI applies its own markup. A field longer than 24 tokens is cut
to a window of 24 tokens around a match, with `…` where text is left out.

When a query matches in more than one field, `snippets` holds a `Snippet` for
each of them, in `title`, `abstract`, `body` order, so a result can show the
match in the title and the passage in the body together:

```python
from sci_etl_core.search import parse_query

for hit in await text_store.search(parse_query("dwarf OR photometr*"), limit=10):
    for snippet in hit.snippets:
        marked = [snippet.text[start:end] for start, end in snippet.highlights]
        print(f"{hit.record_id} {snippet.field}: {snippet.text} {marked}")
```

A field appears in `snippets` only when a matched word is highlighted in it.
The two text stores highlight the same words, except on the queries where FTS5
also counts a word inside a part of the query that fails to match, which
`InMemoryTextSearchStore` documents.

`passage_snippet(query, text)` builds a `Snippet` of any other text in the same
way, highlighting every word of the query that isn't negated. The hybrid
searcher uses it for the passages the semantic leg finds.
