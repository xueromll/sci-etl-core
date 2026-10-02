# When not to use it

`sci-etl-core` does one job: scientific papers in, structured and searchable
data out. This page lists the cases where it is the wrong tool, or where you
would build more yourself than you might expect, so you can decide before you
install it.

## You need a few values from a handful of papers

State files, listing cursors, resumable runs, and caches pay off when a
corpus is too large to read, when you rerun extraction as new papers appear,
or when you need to trace each value back to its source. For a few papers you
already have, reading them, or pasting them into a chat assistant, is faster
than writing prompts, an entity model, and a pipeline.

## Your papers aren't on a bundled source

The bundled extractors cover arXiv, PubMed, Semantic Scholar, and OpenAlex.
bioRxiv, ChemRxiv, Crossref, publisher websites, and a folder of PDFs on your
disk need an `AsyncExtractor` of your own. The contract is three methods, as
[Writing an extractor](../guide/sources.md#writing-an-extractor) shows, but
if you don't want to write one, the pipeline has nothing to run on. The
parsers, search, and LLM components still work on their own.

## The values you need are behind a paywall

Full text comes only from open sources: arXiv LaTeX and PDFs, PubMed Central
JATS XML, and the open-access PDFs that Semantic Scholar and OpenAlex link
to. The library never logs in to a publisher or uses institutional access.
When a paper has no open full text, its record falls back to the abstract,
so for a field where most papers are paywalled, most records give the LLM
only an abstract to read.

## The values live in figures or scanned pages

`PdfPlumberParser` reads the text layer of a PDF, including its tables. It
does no OCR and doesn't read images, so a value that appears only in a plot,
a figure, or a scanned page is invisible to extraction. When a PDF yields no
text at all, the record falls back to the abstract.

## Every value must be correct without review

An LLM reads each paper, so a value can be wrong, misattributed, or missing.
Typed entities, record validators, and [claims](../guide/claims.md) that keep
the sentence each value was read from help you find mistakes and check them;
they don't remove them. The same prompt can also give different answers from
another model or model version, and
[response caching](../guide/llm-caching.md) repeats earlier answers rather
than making the model deterministic. If every value must be right, such as
for a regulatory filing or a clinical decision, budget for checking each one
by hand, or extract without an LLM.

## You need systematic-review completeness

A run can miss relevant papers in three ways:

- **Source caps.** PubMed serves the first 9,999 results of a query and
  Semantic Scholar the first 1,000. Narrower queries, such as date ranges,
  reach the rest, as [Run semantics](../guide/run-semantics.md#capped-listings)
  explains.
- **Automated screening.** The relevance filter decides from the title and
  abstract, with an LLM or by embedding similarity, so a relevant paper can be
  marked irrelevant and never fetched.
- **Missing full text.** A paper read only from its abstract can yield no
  values even when its body has them.

For a review that must account for every included and excluded paper, use
dedicated screening software with human reviewers, and use this library, if
at all, on the papers that screening includes.

## You can't send paper text to an LLM

Each relevant record costs at least one LLM call over its full text, so cost
grows with the corpus. Any endpoint that speaks the OpenAI chat API works,
including local servers such as vLLM, llama.cpp, and Ollama, so the text can
stay on your machine. A provider without such an endpoint needs an
`AsyncLLMClient` of your own. With no LLM at all, entity extraction doesn't
run, but the search and semantic memory components still do: the SQLite text
index needs only the standard library, and `AsyncSentenceTransformerEmbedder`
embeds locally.

## You need a search service or a large vector database

Search runs on your machine over SQLite files:

- `AsyncSqliteEmbeddingStore` scores every stored vector on each query and
  keeps the vectors in memory, so query time and memory use grow with the
  corpus. There is no approximate-nearest-neighbor index yet; the
  [roadmap](../project/roadmap.md#later) lists it as waiting on a corpus that
  needs it.
- State managers rely on local file locks and a single SQLite writer, and
  distributed execution is not planned. Large corpora are covered by sharding
  them across independent runs, each with its own state.
- There is no server, authentication, or multi-user access.

For a hosted, multi-user service or interactive semantic search over a very
large corpus, put the data in a dedicated search engine or vector database,
either by exporting it or through an `AsyncEmbeddingStore` of your own.

## You search Chinese, Japanese, or Korean text, or need substring matches

The text index splits words on spaces and punctuation, as SQLite's
`unicode61` tokenizer does. A run of Chinese, Japanese, or Korean characters
without spaces is indexed as one token, so searching for a word inside it
finds nothing, and a prefix query matches only from the start of the run.
Matching inside words, such as finding `galaxy` in `protogalaxy`, isn't
supported either. Semantic search over embeddings doesn't depend on the
tokenizer.

## You want to write components as blocking code

`ETLPipeline` runs a pipeline from blocking code, as
[Blocking usage](blocking-usage.md) shows, but the extractor, relevance
filter, entity extractor, LLM client, exporter, and state manager contracts
are asynchronous. A component you write yourself has to be an `async`
implementation; blocking versions of these contracts are not planned. Parsers
and pandas processors stay blocking.

## You need a 1.0 stability guarantee

The library is at 0.6. Every planned breaking change before 1.0 has shipped,
and a deprecated name keeps working for at least two minor releases, but
provisional names such as those in `sci_etl_core.claims` may still change in
a minor release. Pin a minor range, such as `>=0.6,<0.7`, and read the
[migration guide](../project/migration.md) before upgrading.

## You want a graphical tool

The library is a Python API. [sci-etl-cli](../cli/index.md) runs pipelines
from a YAML file without wiring code, but it is still a command-line tool.
Neither ships a graphical interface; you build your own, as udg-catalogue
does with its dashboard, and
[Building a user interface](../guide/search/user-interfaces.md) describes
what the search components give it to render.

## Your documents aren't scientific papers

The parsers read PDF, HTML, DOCX, LaTeX, and JATS XML from any source, but
the extractors, record metadata, and search fields (title, abstract, and
body) assume papers. Patents, legal filings, news, and web pages fit poorly,
and features for them are outside the library's scope. A general
document-processing framework suits them better.

## If none of these apply

Start with [Installation](installation.md) and the
[Quick start](quick-start.md).
