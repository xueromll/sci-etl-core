# 本地检索与发现

在向量记忆旁边建立文本索引，可以获得布尔检索、融合关键词排名与语义排名的混合检索、元数据
分面以及相关论文图。这些功能都位于 `sci_etl_core.search` 中，只需要标准库的 `sqlite3`，
因此在不带任何 extra 的 `pip install sci-etl-core` 上就能使用。`search` extra 不会安装
任何东西，它只是让依赖文件说明为什么需要这个包。只有语义检索部分需要 `embeddings` extra。

## 从流水线建立索引 {#indexing-from-the-pipeline}

本示例扩展了[语义记忆](../semantic-memory.md)中的示例，让每条相关记录同时为两种检索建立
索引：

```python
import os

from sci_etl_core import AsyncCompositeIngestor
from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)
from sci_etl_core.search import AsyncHybridSearcher, AsyncSearchIndexer, AsyncSqliteFts5Store

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
vector_store = AsyncSqliteEmbeddingStore("memory.db")
text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))

ingestor = AsyncCompositeIngestor(
    AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=vector_store),
    AsyncSearchIndexer(store=text_store),
)


async def show_matches(query: str) -> None:
    searcher = AsyncHybridSearcher(text_store, AsyncSimilarArticleFinder(embedder, vector_store))
    outcome = await searcher.search(query, top_k=10)
    if outcome.degraded:
        print(f"Degraded: {', '.join(outcome.degraded)}")
    for hit in outcome.hits:
        print(f"{hit.score:.4f}  {hit.record_id}  {hit.title}")
```

把摄取器加入[快速开始](../../getting-started/quick-start.md)中的流水线：

```python
pipeline = AsyncETLPipeline(
    ...,
    memory_ingestor=ingestor,
    closeables=[client, llm, embedder, vector_store, text_store],
)
```

- **关闭存储。** `text_store` 与 `vector_store` 出于同样的原因放进 `closeables`，因为这是
  一个一次性脚本：流水线拥有这两个存储，因此 `show_matches` 必须在 `async with pipeline`
  内部运行。长期运行的应用程序则应遵循[存储的所有权](store-ownership.md)。
- **记忆故障。** 建立索引时出现的 `SearchStoreError` 会以警告
  `Memory ingest failed for <record_id> in AsyncSearchIndexer: ...` 记录到
  `sci_etl_core.ingest_async` 记录器，而该记录的文本块仍会被嵌入，其实体仍会被导出。同样，
  嵌入故障也不会影响文本索引。`SearchQueryError` 不属于记忆故障，会导致该记录失败。
- **摄取器顺序。** `AsyncCompositeIngestor` 返回其第一个摄取器的计数，因此请把分块摄取器
  放在第一位；把 `AsyncSearchIndexer` 放在第一位会抛出 `ValueError`。不使用嵌入时，直接把
  `AsyncSearchIndexer` 传给 `memory_ingestor=`。
- **索引的内容。** 每条记录一个文档，包含其标题、摘要、全文和 `metadata`。重新摄取一条
  记录会替换它的文档；标题、摘要和正文全为空的记录会被删除。

## 本节内容 {#in-this-section}

- [查询语法](query-syntax.md)：布尔查询语言及其解析器。
- [排序检索与过滤](ranked-search.md)：`search` 与 `filter_ids` 的区别，以及摘要片段。
- [混合检索](hybrid-search.md)：将 BM25 与嵌入相似度融合。
- [过滤器与分面](filters-and-facets.md)：元数据过滤器和范围过滤器，分面计数和范围计数。
- [文本存储](text-stores.md)：内存索引和 SQLite FTS5 索引。
- [从向量记忆回填](backfill.md)：根据已存储的文本块构建文本索引。
- [发现图](discovery-graphs.md)：相关论文图。
- [构建用户界面](user-interfaces.md)：界面所渲染的读模型。
- [存储的所有权](store-ownership.md)：由谁、在何时关闭存储。
