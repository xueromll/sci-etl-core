# Supported sources

Every source has its own protocol, pagination model, ID scheme, and full-text
formats, so each one gets its own `AsyncExtractor` rather than a single
extractor with switches for every source.

| Source | Extractor | Record id | Paging | Full text |
|--------|-----------|-----------|--------|-----------|
| arXiv | `AsyncArxivExtractor` | arXiv id with version | offsets | LaTeX source, then PDF, then abstract |
| PubMed | `AsyncPubMedExtractor` | PMID | offsets, first 9,999 results | PubMed Central JATS when the paper has a PMC id, else abstract |
| Semantic Scholar | `AsyncSemanticScholarExtractor` | paper id | offsets, first 1,000 results | Open-access PDF with a `pdf_parser`, else abstract |
| OpenAlex | `AsyncOpenAlexExtractor` | work id, such as `W2741809807` | OpenAlex cursors, no cap | Open-access PDF with a `pdf_parser`, else abstract |
| bioRxiv, ChemRxiv | Not bundled | | | Adapt `AsyncArxivExtractor` |
| Crossref | Not bundled | | | Implement your own `AsyncExtractor` |

An extractor that pages by offset is an `OffsetListing`, which `newest_first`
runs and `run(start_index=)` above 0 need. When a source stops at its own
result cap, its extractor marks the page that reaches the cap as `truncated`:
the run completes, and the next run pages the reachable results again instead
of stopping at the cap. Processed records are skipped by id, so that rescan
costs listing requests, not LLM calls. To avoid it, narrow the query, for
example by date range. [Run semantics](run-semantics.md#capped-listings) has
the details.

The bundled extractors share the retry behavior described in
[Retries](retries.md) and take a `rate_limiter` ([Rate limiting](rate-limiting.md)).
Each fills `RawRecord.metadata` with `authors` and `categories`, and with
`published` and `year` when the source has a date, so search filters and
facets work the same across sources. Sources other than arXiv also store
`pdf_url` or `pmcid` there, which `fetch_full_text` reads.

## PubMed

```python
from sci_etl_core import AsyncPubMedExtractor
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncPubMedExtractor(
    client,
    api_key=ncbi_api_key,
    tool="my-project",
    email="you@example.org",
    rate_limiter=build_rate_limiter(max_rate=9, time_period=1.0),
)
await pipeline.run("dark matter[tiab] AND 2020:2026[dp]", total_limit=200, newest_first=True)
```

The query uses PubMed search syntax. Results are newest first (`sort="pub_date"`),
so `newest_first=True` fits. Each listing page costs two requests, and NCBI
allows 3 requests per second without an API key and 10 with one, so read the
key from the environment and set a limiter below that. E-utilities pages
through the first 9,999 results of a search, even with its history server, so
the page that reaches them is `truncated`. Metadata adds `journal`, and `doi`
and `pmcid` when known; `categories` are MeSH headings.

## Semantic Scholar

```python
from sci_etl_core import AsyncSemanticScholarExtractor
from sci_etl_core.parsers import PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncSemanticScholarExtractor(
    client,
    PdfPlumberParser(),
    api_key=semantic_scholar_key,
    year="2020-",
    fields_of_study="Physics",
    rate_limiter=build_rate_limiter(max_rate=1, time_period=1.0),
)
```

The relevance search returns only its first 1,000 results and isn't ordered by
date, so run it without `newest_first`; the page that reaches the 1,000th
result is `truncated`. Metadata adds `venue`, and `doi`, `arxiv_id`, and `pmid`
when known.

## OpenAlex

```python
from sci_etl_core import AsyncOpenAlexExtractor

extractor = AsyncOpenAlexExtractor(
    client,
    filter="type:article,from_publication_date:2020-01-01",
    mailto="you@example.org",
)
await pipeline.run("ultra-diffuse galaxies", total_limit=500)
```

Results are newest first by default (`sort="publication_date:desc"`). Paging
uses OpenAlex's cursors, so a listing is not limited to its first 10,000
results, but the extractor is not an `OffsetListing` and does not support
`newest_first` runs. When a run reaches the end of the listing, the next run
starts again from the first page and skips processed works by id. A cursor
OpenAlex rejects restarts the listing once. `mailto` joins OpenAlex's polite
pool. Abstracts are rebuilt from OpenAlex's inverted index. Metadata
adds `doi`, `venue`, and `references`, the ids of the works a paper cites.

## Document formats

Besides the PDF, LaTeX, and HTML parsers the extractors use, two parsers read
formats you may get from other sources:

- **`DocxParser`** reads Word `.docx` files with the standard library and
  `lxml`: paragraphs in order, tables as tab-separated rows, and, with
  `include_notes=True`, footnotes and endnotes.
- **`JatsXmlParser`** reads JATS XML, the format of PubMed Central and many
  publishers. `extract_text` returns the title, abstract, and body without the
  reference list, and `parse_article` returns a `JatsArticle` with sections,
  authors, keywords, journal, publication date, identifiers, and references.

```python
from sci_etl_core.parsers import JatsXmlParser

article = JatsXmlParser().parse_article(xml_bytes)
print(article.title, article.doi, [section.title for section in article.sections])
```

Both parse XML without resolving entities or fetching DTDs, and raise
`ParsingError` for bytes they can't read.

## Writing an extractor

The pipeline works with any class that implements this contract:

```python
from sci_etl_core import AsyncExtractor, ListingPage
from sci_etl_core.models import RawRecord


class MySourceExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...
```

- **`fetch_page`** fetches and parses one page. `cursor=None` is the first
  page; any other cursor is a `next_cursor` an earlier page returned, possibly
  in an earlier run. It returns a `ListingPage` with every record it could
  read, the number of entries on the page, counting entries it could not read,
  and the next cursor, or `None` on the last page. The pipeline skips
  processed records itself. A source that stopped at its own result cap
  returns `truncated=True`.
- Errors: if the source can't be reached, raise `UpstreamError` instead of
  returning an empty page; if it rejects the request outright, raise
  `ExtractionError`; if the payload can't be read, raise
  `MalformedResponseError`. Each aborts the run. If the source no longer
  accepts a cursor, raise `StaleCursorError`, and the run restarts the listing
  from the first page once.
- **`cursor_for_offset`** is only for a source that pages by offset. It makes
  the extractor an `OffsetListing`; leave it out when the cursors are opaque
  tokens.
- **`fetch_full_text`** returns the best text available for a record.

An extractor written for 0.4, with `search` and `parse_listing`, runs in 0.5.x
through `LegacyExtractorAdapter`, which is deprecated and removed in 0.6.

The full contract for every component type is listed under
[Adding a new component](../project/contributing.md#adding-a-new-component),
and the [extractor API reference](../reference/extractors.md) documents the
base classes.
