# Claims and provenance

A claim is one value or statement extracted from a paper, stored with the
paper it came from, the sentence it was read from, and the model, prompt, and
schema that produced it. Claims let a table answer "which paper says so?" for
every value, keep conflicting reports side by side, and find every value a
prompt fix must redo.

!!! note "Provisional"
    `sci_etl_core.claims` is new in 0.6.0 and provisional: a name may change
    in a minor release, with a CHANGELOG entry, until a known consumer depends
    on it.

## Extracting claims

`AsyncLLMClaimExtractor` asks the model for `ClaimDraft` objects, validates
them, locates each draft's quote in the text the model was sent, and returns
`Claim` objects. `AsyncClaimStoreExporter` stores them record by record:

```python
import os

from sci_etl_core import AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.claims import (
    AsyncClaimStoreExporter,
    AsyncLLMClaimExtractor,
    AsyncSqliteClaimStore,
    AsyncSqliteRejectionStore,
)

CLAIM_PROMPT = (
    "List every measurement of an ultra-diffuse galaxy in the paper. Reply with JSON: "
    '{"claims": [{"kind": "measurement", "subject": "...", "predicate": "effective_radius", '
    '"quantity": {"verbatim": "2.9 kpc", "value": 2.9, "unit_text": "kpc"}, '
    '"context": {"band": "g"}, "quote": "the sentence, copied exactly"}]}.'
)

llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"], base_url="https://api.openai.com/v1", model="gpt-4o-mini"
)
claims = AsyncSqliteClaimStore("data/claims.db")
rejections = AsyncSqliteRejectionStore("data/rejections.db")

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=AsyncLLMClaimExtractor(llm, CLAIM_PROMPT, rejections=rejections),
    exporter=AsyncClaimStoreExporter(claims),
    state_manager=state_manager,
    closeables=[llm, claims, rejections],
)
```

Subclass `ClaimDraft` to narrow `predicate` or the `context` keys for your
field, and pass the subclass as `schema=`. The model never supplies ids,
offsets, or provenance; code computes them.

## What a claim holds

| Field | Meaning |
|-------|---------|
| `claim_id` | a digest of the record, kind, subject, predicate, object, polarity, context, the quantity's verbatim text, the span, and the schema hash |
| `kind` | `"measurement"`, which needs a `quantity`, or `"assertion"`, which needs an `object` |
| `subject`, `predicate`, `object` | what the claim is about, as the paper names it |
| `quantity` | the number as the paper writes it: `verbatim`, `value`, `unit_text`, `qualifier`, `uncertainty` |
| `statistics` | effect sizes, confidence bounds, *p*, test statistics, group sizes, each optional |
| `context` | conditions such as band or sample, as sorted key–value pairs |
| `span` | the `record_id`, the start and end offsets of the sentence or sentences the quote was found in, and the quote itself |
| `stamp` | the model, prompt hash, schema hash, and library release |

The model, prompt, and library release are left out of `claim_id` on purpose:
re-extracting a paper with another model gives the same ids wherever the
fields match, with a new stamp. Subjects are compared exactly, so `"DF44"` and
`"DF 44"` are different claims; resolving names is a later step that never
rewrites claims. `Claim.to_row()` gives one flat mapping, the shape the stores
and the CSV and JSON Lines exporters write.

## Grounding

`locate_quote(text, quote)` finds the quote in the text the model was sent,
exactly after collapsing whitespace, or else fuzzily with `difflib` at
`min_ratio` (0.9) or above, and snaps the match to whole sentences. The
sentence splitter knows scientific prose: `et al.`, `Fig. 3`, `Eq. (2)`,
`i.e.`, `R.A.`, and decimals do not end a sentence. A draft whose quote is not
found is ungrounded: it is logged, put in the rejection store with the code
`"ungrounded"`, and not returned.

## Stores

`InMemoryClaimStore` and `AsyncSqliteClaimStore` share one contract:

- `replace_record(record_id, claims)` replaces a record's claims in one
  transaction and returns the new revision. An empty list clears the record,
  which is what happens when a re-extraction finds nothing, because the
  pipeline writes every processed record.
- `claims_for_records(record_ids)` reads claims back, in stored order.
- `changes_since(revision)` pages through what changed, by revision, which only
  grows, so a downstream job can pick up where it stopped.

The SQLite store indexes claims by record, by `(subject, predicate, object)`,
by context pair, and by canonical kind and value, and records its schema
version, so a later sci-etl-core opens files written by 0.6.0.

A store fault in `AsyncClaimStoreExporter.write` fails the record, which is
retried on the next run and counts one attempt, like any failing record. It is
not a memory fault.
