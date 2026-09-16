# Query syntax

| Construct | Example | Matches |
|-----------|---------|---------|
| Term | `galaxy` | the word, ignoring case and accents, so `Müller` matches `Muller` |
| Phrase | `"dwarf galaxy"` | the words next to each other, in order |
| Prefix | `photometr*` | any word starting with `photometr` |
| Field scope | `title:quasar`, `title,abstract:"dwarf galaxy"` | only in the named fields: `title`, `abstract`, `body` |
| And | `a AND b`, `a && b`, `a b` | both |
| Or | `a OR b`, `a \|\| b` | either |
| Not | `NOT a`, `-a` | documents without `a` |
| Grouping | `(a OR b) -c` | |

`NOT` binds tightest, then `AND`, then `OR`. Operators are upper case, so
`and` is an ordinary word. A word the tokenizer splits, such as `H-alpha`, is
searched as a phrase of its parts.

## Parsing

Parsing is pure and synchronous, so a query bar can run it on every keystroke.
A malformed query raises `SearchQueryError`, whose `position` and `token` point
at the fault, and `describe` returns the parsed words and phrases as
`QueryChip`s for display:

```python
from sci_etl_core import SearchQueryError
from sci_etl_core.search import describe, parse_query

try:
    chips = describe(parse_query("title:quasar (blazar OR -dwarf"))
except SearchQueryError as exc:
    print(f"{exc} (column {exc.position}: {exc.token!r})")
```
