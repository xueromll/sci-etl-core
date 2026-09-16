# Supported sources

`AsyncArxivExtractor` is the only extractor that ships with the library. Every
source has its own protocol, pagination model, ID scheme, and full-text
formats, so each one gets its own `AsyncExtractor` rather than a single
extractor with switches for every source.

| Source | Status | How to use it |
|--------|--------|---------------|
| arXiv | Bundled | `AsyncArxivExtractor` |
| bioRxiv | Not bundled | Adapt `AsyncArxivExtractor` |
| ChemRxiv | Not bundled | Adapt `AsyncArxivExtractor` |
| PubMed | Not bundled | Implement your own `AsyncExtractor` |
| Crossref | Not bundled | Implement your own `AsyncExtractor` |

## Writing an extractor

The pipeline works with any class that implements this contract:

```python
from sci_etl_core import AsyncExtractor
from sci_etl_core.models import RawRecord


class MySourceExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None: ...

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...
```

- **`search`** returns one raw listing page. If the source can't be reached,
  it raises `UpstreamError` instead of returning an empty value; if the source
  rejects the request outright, it raises `ExtractionError`. Either one aborts
  the run.
- **`parse_listing`** returns the records whose ids aren't in `seen_ids`, plus
  the number of entries on the page, counting the skipped ones. A count of `0`
  ends the run. If the payload can't be read, it raises
  `MalformedResponseError`.
- **`fetch_full_text`** returns the best text available for a record.

The full contract for every component type is listed under
[Adding a new component](../project/contributing.md#adding-a-new-component),
and the [extractor API reference](../reference/extractors.md) documents the
base classes.
