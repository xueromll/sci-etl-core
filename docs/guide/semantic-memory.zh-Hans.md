# 语义记忆

语义记忆是可选功能，需要 `embeddings` extra。传入 `memory_ingestor` 后，每条相关记录的
全文都会被分块并嵌入到向量存储中。之后就可以按语义检索该存储：

```python
import os

from sci_etl_core.embeddings import (
    AsyncChunkIngestor,
    AsyncOpenAIEmbedder,
    AsyncSimilarArticleFinder,
    AsyncSqliteEmbeddingStore,
    SlidingWindowChunker,
)

embedder = AsyncOpenAIEmbedder(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="text-embedding-3-small",
)
store = AsyncSqliteEmbeddingStore("memory.db")
ingestor = AsyncChunkIngestor(chunker=SlidingWindowChunker(), embedder=embedder, store=store)


async def show_similar(text: str) -> None:
    finder = AsyncSimilarArticleFinder(embedder, store)
    for record_id, score, metadata in await finder.find_similar_articles(text, top_k=5):
        print(f"{score:.2f}  {record_id}  {metadata['title']}")
```

把摄取器加入[快速开始](../getting-started/quick-start.md)中的流水线，并把嵌入器和存储列入
它的 `closeables`：

```python
pipeline = AsyncETLPipeline(..., memory_ingestor=ingestor, closeables=[client, embedder, store])
```

- **存储的内容。** 摄取在相关性判断之后运行，因此只有相关记录会被嵌入。
  `SlidingWindowChunker` 默认使用 350 词的窗口，重叠 50 词。重新摄取一条记录会替换它的
  所有文本块，因此当文本现在产生的段落变少时，也不会留下过时的内容。
- **故障。** 摄取期间出现的 `EmbeddingError` 或 `EmbeddingStoreError` 会被记录，而该记录
  的实体仍会被导出。这包括记忆文件不是 SQLite 数据库的情况，以及嵌入器返回的向量数与段落数
  不一致的情况。
- **存储。** `InMemoryEmbeddingStore()` 适合测试和短时运行。`AsyncSqliteEmbeddingStore`
  使用标准库的 `sqlite3` 模块持久化向量，每次查询都会为所有已存储的向量打分。它在两次查询
  之间把向量保存在内存中，只有在发生写入（来自本存储或其他进程）之后才重新读取，因此内存
  占用会随存储增长。它会串行化对连接的访问，因此并发处理的记录可以共享同一个存储，而且
  每次写入都是一个事务。含有 NaN 或无穷大的已存储向量永远不会出现在结果中。
- **自定义存储。** `AsyncEmbeddingStore` 的子类需要实现 `add`、`delete_record`、`query`
  和 `count`。`replace_record` 默认先删除再添加；如果你的后端能原子地完成这两步，请重写它。
- **读取记忆。** `finder.find_best_chunks(text, top_k=5)` 与 `find_similar_articles` 一样
  对文章排序，但返回每篇文章最好的 `SearchHit`，其中包含文本块内容，便于展示匹配的段落。
  存储的 `iter_records()` 以 `StoredRecord` 的形式逐条产出每条记录的段落，不加载向量。
- **本地嵌入。** `AsyncSentenceTransformerEmbedder("all-MiniLM-L6-v2")` 无需网络调用即可
  生成嵌入。它需要 `embeddings-local` extra，在构造时加载模型，也接受通过 `model=` 传入
  预先加载的模型。

## 不用 LLM 判断相关性 {#relevance-without-an-llm}

当记录的标题和摘要与任一参考文本足够接近时，`AsyncEmbeddingRelevanceFilter` 会保留它：

```python
from sci_etl_core import AsyncEmbeddingRelevanceFilter

relevance_filter = AsyncEmbeddingRelevanceFilter(
    embedder=embedder,
    reference_texts=["ultra-diffuse galaxies", "low surface brightness galaxies"],
    threshold=0.35,  # 最小余弦相似度
)
```

## 同时按关键词检索 {#searching-by-keyword-too}

若要让相同的记录也支持布尔检索，请参阅[本地检索与发现](search/index.md)。其 SQLite 文本
索引 `AsyncSqliteFts5Store` 是需要与嵌入存储一起列入 `closeables` 的另一个存储，它的
`search` extra 不会安装任何东西。在添加文本索引之前就已填充的记忆，可以根据其已存储的
文本块建立索引；参见[从向量记忆回填](search/backfill.md)。
