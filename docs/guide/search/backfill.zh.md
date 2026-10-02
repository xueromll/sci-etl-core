# 从向量记忆回填

一个启用了语义记忆但没有文本索引的部署，其 `AsyncSqliteEmbeddingStore` 中已经保存了每条
相关记录的全文（按文本块切分）。`backfill_text_index` 根据这些文本块构建文本索引，因此无需
重新获取或嵌入任何内容：

```python
import asyncio

from sci_etl_core.embeddings import AsyncSqliteEmbeddingStore, SlidingWindowChunker
from sci_etl_core.search import AsyncSqliteFts5Store, backfill_text_index


async def backfill() -> None:
    vector_store = AsyncSqliteEmbeddingStore("memory.db")
    text_store = AsyncSqliteFts5Store("search.db", facet_keys=("categories", "year"))
    try:
        report = await backfill_text_index(
            vector_store,
            text_store,
            overlap_words=SlidingWindowChunker().overlap_words,
        )
        print(f"{report.indexed} indexed, {report.skipped_existing} already there, {report.skipped_empty} empty")
    finally:
        await vector_store.aclose()
        await text_store.aclose()


asyncio.run(backfill())
```

在没有任何流水线向这两个存储写入时运行它一次，然后按照[本地检索与发现](index.md)所示，
向流水线添加一个 `AsyncSearchIndexer`，让新记录在到达时就被索引。

## 重叠的文本块 {#overlapping-chunks}

`SlidingWindowChunker` 让相邻文本块相互重叠（默认 50 个词），以免任何段落在窗口边界处被
截断。如果按原样拼接文本块，这些词会重复出现，BM25 会把边界处的每个词计算两次。回填通过
`merge_passages` 去除重叠：当每个文本块的前 `overlap_words` 个词与前一个文本块的结尾重复
时，就丢弃它们，于是正文中每个词只出现一次。

请传入写入这些文本块的分块器的 `overlap_words`。如果使用的是
`SlidingWindowChunker(chunk_words, overlap_words)`，就传入相同的 `overlap_words`；如果
当初省略了它，就像示例那样，从以同样方式构造的分块器中读取。开头几个词与前一个文本块结尾
不重复的文本块会被完整保留，因此值传错时，只会在正文中留下重复的词，而不会删掉文本。

还原后的正文按分块器的切分方式在词之间使用单个空格；换行和段落间距会丢失，但这不影响匹配
结果。

## 回填文档包含的内容 {#what-a-backfilled-document-holds}

向量记忆保存的信息比流水线当时掌握的少，因此回填的文档默认包含：

| 字段 | 值 |
|------|----|
| `title` | 与该记录的文本块一同存储的 `title` |
| `abstract` | 空，因为文本块中不包含摘要 |
| `body` | 合并后的文本块 |
| `metadata` | 其他文本块元数据，例如 `source_url` |

`AsyncChunkIngestor` 不会把 `RawRecord.metadata` 与文本块一同存储，因此回填的文档没有
`categories`、`year` 或其他分面标签，基于这些键的过滤器不会匹配它。如果你在别处（例如导出
的 CSV 中）保存了这些元数据，可以传入一个 `build_document` 来补充。它接收 `StoredRecord`
和合并后的正文，返回要索引的 `SearchDocument`，或返回 `None` 以跳过该记录：

```python
from sci_etl_core.search import SearchDocument, backfill_text_index, stored_record_document


def with_catalogue_metadata(record, body):
    document = stored_record_document(record, body)
    if document is None or record.record_id not in catalogue:
        return document
    entry = catalogue[record.record_id]
    document.abstract = entry["abstract"]
    document.metadata.update(categories=entry["categories"], year=entry["year"])
    return document


report = await backfill_text_index(
    vector_store, text_store, overlap_words=50, build_document=with_catalogue_metadata
)
```

## 已在索引中的记录 {#records-already-in-the-index}

流水线已经索引过的记录带有摘要和元数据，而回填的文档缺少这些信息，因此回填不会改动它，
而是把它计入 `skipped_existing`。传入 `replace_existing=True` 可以用向量记忆覆盖每条记录，
例如在从头重建文本索引之后。文本索引中不在向量记忆里的记录永远不会被改动。

- **分批。** 记录每次按 `batch_size` 条读取和写入（默认 100），且不加载任何向量，因此在大型
  存储上内存占用也保持平稳。
- **其他向量存储。** `InMemoryEmbeddingStore` 和 `AsyncSqliteEmbeddingStore` 可以通过
  `iter_records` 列出其记录。未实现该方法的自定义 `AsyncEmbeddingStore` 会抛出
  `NotImplementedError`。
- **所有权。** `backfill_text_index` 不会关闭任何一个存储；请像示例那样自行关闭。
