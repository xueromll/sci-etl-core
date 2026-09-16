# Query syntax

| Construct | Example | Matches |
|-----------|---------|---------|
| Term | `galaxy` | the word, ignoring case and accents, so `Müller` matches `Muller` |
| Phrase | `"dwarf galaxy"` | the words next to each other, in order |
| Prefix | `photometr*` | any word starting with `photometr` |
| Field scope | `title:quasar`, `title,abstract:"dwarf galaxy"` | only in the named fields: `title`, `abstract`, `body` |
| Near | `NEAR(dwarf "dark matter" halo*, 5)`, `title:NEAR(dwarf halo)` | all the terms and phrases in one field, within 5 tokens of each other (10 by default), in any order |
| And | `a AND b`, `a && b`, `a b` | both |
| Or | `a OR b`, `a \|\| b` | either |
| Not | `NOT a`, `-a` | documents without `a` |
| Grouping | `(a OR b) -c` | |

`NOT` binds tightest, then `AND`, then `OR`. Operators are upper case, so
`and` is an ordinary word. A word the tokenizer splits, such as `H-alpha`, is
searched as a phrase of its parts.

## Proximity

`NEAR(...)` takes terms, phrases, and prefix terms separated by spaces, then
optionally a comma and a whole number of tokens. With the occurrences chosen
so that the one starting last starts at token `p`, every other operand must
end at most that many tokens before `p`: `NEAR(a b, 2)` matches `a x x b` and
`b x a` but not `a x x x b`.

- **Scope the group, not its parts.** `abstract:NEAR(dwarf halo)` looks in the
  abstract; a field scope inside the parentheses, such as
  `NEAR(title:dwarf halo)`, is a `SearchQueryError`.
- **Only words inside.** `AND`, `OR`, `NOT`, `-`, `&&`, `||`, and nested
  parentheses are rejected inside a group. Negate or combine the whole group
  instead, as in `quasar -NEAR(dwarf halo, 3)`.
- **Short forms.** A group with one operand, such as `NEAR(dwarf)`, is that
  term. A group holding one quoted phrase, such as `NEAR("dwarf halo", 3)`,
  searches for the phrase's words near each other, not for the phrase.
- **Upper case, no space.** `NEAR` must be upper case and directly followed by
  `(`; `near(a b)` and `NEAR (a b)` are read as the word `near` and the terms
  `a` and `b`.

A `NEAR` group ranks, filters, and highlights like any other term, in both
text stores. In a hybrid search its words are embedded like the rest of the
query, except its prefix terms. `describe` returns a group as one `QueryChip` whose `near` is its
distance.

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
