# 支持的来源

每个来源都有自己的协议、分页模型、ID 方案和全文格式，因此每个来源都有各自的
`AsyncExtractor`，而不是用一个带有各种来源开关的提取器。

| 来源 | 提取器 | 记录 id | 分页 | 全文 |
|------|--------|---------|------|------|
| arXiv | `AsyncArxivExtractor` | 带版本号的 arXiv id | 偏移量 | LaTeX 源文件，其次 PDF，再次摘要 |
| PubMed | `AsyncPubMedExtractor` | PMID | 偏移量，前 9,999 条结果 | 论文有 PMC id 时使用 PubMed Central 的 JATS，否则使用摘要 |
| Semantic Scholar | `AsyncSemanticScholarExtractor` | 论文 id | 偏移量，前 1,000 条结果 | 提供 `pdf_parser` 时使用开放获取 PDF，否则使用摘要 |
| OpenAlex | `AsyncOpenAlexExtractor` | 作品 id，例如 `W2741809807` | OpenAlex 游标，无上限 | 提供 `pdf_parser` 时使用开放获取 PDF，否则使用摘要 |
| bioRxiv、ChemRxiv | 未内置 | | | 改造 `AsyncArxivExtractor` |
| Crossref | 未内置 | | | 实现你自己的 `AsyncExtractor` |

按偏移量分页的提取器是 `OffsetListing`，`newest_first` 运行以及 `start_index` 大于 0 的
`run(start_index=)` 都需要它。当来源在自身的结果上限处停止时，其提取器会把达到上限的那一页
标记为 `truncated`：本次运行正常完成，下一次运行会重新翻阅可访问的结果，而不是停在上限处。
已处理的记录会按 id 跳过，因此这种重新扫描只消耗列表请求，不消耗 LLM 调用。要避免重新扫描，
请缩小查询范围，例如按日期范围。详情见[运行语义](run-semantics.md#capped-listings)。

内置提取器共享[重试](retries.md)中描述的重试行为，并接受 `rate_limiter`
（[速率限制](rate-limiting.md)）。每个提取器还接受 `max_download_bytes`，用于在解码后限制
每个响应体的大小：过大的列表页会抛出 `ExtractionError`，过大的全文下载会被记录并跳过。
`LatexTarballParser(max_tex_bytes=)` 以同样方式限制从一个 arXiv e-print 中解压出的 TeX。
每个提取器都会在 `RawRecord.metadata` 中填写 `authors` 和 `categories`，在来源提供日期时
还会填写 `published` 和 `year`，因此检索过滤器和分面在各来源之间的行为一致。arXiv 以外的
来源还会在其中保存 `pdf_url` 或 `pmcid`，供 `fetch_full_text` 读取。

## PubMed {#pubmed}

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

查询使用 PubMed 的检索语法。结果按最新优先排序（`sort="pub_date"`），因此适合使用
`newest_first=True`。每个列表页需要两次请求，而 NCBI 在没有 API 密钥时每秒允许 3 次请求，
有密钥时允许 10 次，因此请从环境中读取密钥，并把限制器设在这个值以下。即使使用其历史服务器，
E-utilities 也只能翻阅检索的前 9,999 条结果，因此到达这些结果的那一页会被标记为
`truncated`。元数据会额外添加 `journal`，已知时还有 `doi` 和 `pmcid`；`categories` 是 MeSH
主题词。

## Semantic Scholar {#semantic-scholar}

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

相关性检索只返回前 1,000 条结果，而且不按日期排序，因此请不要使用 `newest_first`；到达第
1,000 条结果的那一页会被标记为 `truncated`。元数据会额外添加 `venue`，已知时还有 `doi`、
`arxiv_id` 和 `pmid`。

## OpenAlex {#openalex}

```python
from sci_etl_core import AsyncOpenAlexExtractor

extractor = AsyncOpenAlexExtractor(
    client,
    filter="type:article,from_publication_date:2020-01-01",
    mailto="you@example.org",
)
await pipeline.run("ultra-diffuse galaxies", total_limit=500)
```

结果默认按最新优先排序（`sort="publication_date:desc"`）。分页使用 OpenAlex 的游标，因此
列表不限于前 10,000 条结果，但该提取器不是 `OffsetListing`，不支持 `newest_first` 运行。
当一次运行到达列表末尾时，下一次运行会重新从第一页开始，并按 id 跳过已处理的作品。被
OpenAlex 拒绝的游标会让列表重新开始一次。`mailto` 会让你加入 OpenAlex 的礼貌池（polite
pool）。摘要根据 OpenAlex 的倒排索引重建。元数据会额外添加 `doi`、`venue` 和
`references`，即论文所引用作品的 id。

## 文档格式 {#document-formats}

除了提取器所使用的 PDF、LaTeX 和 HTML 解析器之外，还有两个解析器可以读取你可能从其他来源
获得的格式：

- **`DocxParser`** 使用标准库和 `lxml` 读取 Word `.docx` 文件：按顺序读取段落，把表格读成
  以制表符分隔的行；设置 `include_notes=True` 时还会读取脚注和尾注。
- **`JatsXmlParser`** 读取 JATS XML，这是 PubMed Central 和许多出版商使用的格式。
  `extract_text` 返回标题、摘要和正文（不含参考文献列表），`parse_article` 则返回一个
  `JatsArticle`，其中包含章节、作者、关键词、期刊、出版日期、标识符和参考文献。

```python
from sci_etl_core.parsers import JatsXmlParser

article = JatsXmlParser().parse_article(xml_bytes)
print(article.title, article.doi, [section.title for section in article.sections])
```

两者解析 XML 时都不解析实体、不获取 DTD，遇到无法读取的字节时抛出 `ParsingError`。

## 编写提取器 {#writing-an-extractor}

流水线可以与任何实现以下契约的类协作：

```python
from sci_etl_core import AsyncExtractor, ListingPage
from sci_etl_core.models import RawRecord


class MySourceExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...
```

- **`fetch_page`** 获取并解析一页。`cursor=None` 表示第一页；其他任何游标都是之前某一页
  （可能是在之前的某次运行中）返回的 `next_cursor`。它返回一个 `ListingPage`，其中包含它能
  读取的所有记录、该页的条目数（包括无法读取的条目）以及下一个游标；最后一页的下一个游标为
  `None`。流水线会自行跳过已处理的记录。在自身结果上限处停止的来源应返回 `truncated=True`。
- 错误：如果无法连接来源，请抛出 `UpstreamError`，而不是返回空页；如果来源直接拒绝请求，
  请抛出 `ExtractionError`；如果无法读取返回内容，请抛出 `MalformedResponseError`。它们都会
  中止运行。如果来源不再接受某个游标，请抛出 `StaleCursorError`，运行会从第一页重新开始列表
  一次。
- **`cursor_for_offset`** 仅适用于按偏移量分页的来源。它使提取器成为 `OffsetListing`；当
  游标是不透明的令牌时，请不要实现它。
- **`fetch_full_text`** 返回一条记录可获得的最佳文本。

每种组件类型的完整契约列在[添加新组件](../project/contributing.md#adding-a-new-component)
中，[提取器 API 参考](../reference/extractors.md)则记录了各个基类。
