# Supported sources

Every source has its own protocol, pagination model, ID scheme, and full-text
formats, so each one gets its own `AsyncExtractor` rather than a single
extractor with switches for every source.

| Source | Extractor | Record id | Full text |
|--------|-----------|-----------|-----------|
| arXiv | `AsyncArxivExtractor` | arXiv id with version | LaTeX source, then PDF, then abstract |
| PubMed | `AsyncPubMedExtractor` | PMID | PubMed Central JATS when the paper has a PMC id, else abstract |
| Semantic Scholar | `AsyncSemanticScholarExtractor` | paper id | Open-access PDF with a `pdf_parser`, else abstract |
| OpenAlex | `AsyncOpenAlexExtractor` | work id, such as `W2741809807` | Open-access PDF with a `pdf_parser`, else abstract |
| bioRxiv, ChemRxiv | Not bundled | | Adapt `AsyncArxivExtractor` |
| Crossref | Not bundled | | Implement your own `AsyncExtractor` |

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
await pipeline.run(query="dark matter[tiab] AND 2020:2026[dp]", total_limit=200, newest_first=True)
```

The query uses PubMed search syntax. Results are newest first (`sort="pub_date"`),
so `newest_first=True` fits. Each listing page costs two requests, and NCBI
allows 3 requests per second without an API key and 10 with one, so read the
key from the environment and set a limiter below that. E-utilities pages
through the first 10,000 results of a search. Metadata adds `journal`, and
`doi` and `pmcid` when known; `categories` are MeSH headings.

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
date, so run it without `newest_first`. Metadata adds `venue`, and `doi`,
`arxiv_id`, and `pmid` when known.

A query that matches more results than a source serves stops at its cap, and
later runs resume at the cap; see
[capped listings](run-semantics.md#known-limitation-capped-listings).

## OpenAlex

```python
from sci_etl_core import AsyncOpenAlexExtractor

extractor = AsyncOpenAlexExtractor(
    client,
    filter="type:article,from_publication_date:2020-01-01",
    mailto="you@example.org",
)
await pipeline.run(query="ultra-diffuse galaxies", total_limit=500, newest_first=True)
```

Results are newest first by default (`sort="publication_date:desc"`).
OpenAlex pages through the first 10,000 results. `mailto` joins OpenAlex's
polite pool. Abstracts are rebuilt from OpenAlex's inverted index. Metadata
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
