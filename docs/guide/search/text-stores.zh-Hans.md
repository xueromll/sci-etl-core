# 文本存储

- **`InMemoryTextSearchStore(facet_keys=...)`** 适合测试和短时运行。它匹配的记录与
  SQLite 存储完全相同，并使用相同的 BM25 公式打分。
- **`AsyncSqliteFts5Store(path, facet_keys=..., weights=...)`** 会持久化索引。每篇文章的
  文本只存储一次，每次写入都是一个事务，任何 SQLite 故障（包括文件不是数据库的情况）都会
  抛出 `SearchStoreError`。`weights=BM25Weights(title=10.0, abstract=4.0, body=1.0)`
  设置各字段中匹配的权重；这些就是默认值。
- **需要 FTS5。** 该存储要求 Python 所带的 SQLite 在编译时启用了 FTS5，否则在构造时抛出
  `SearchStoreError`。`fts5_available()` 可以预先检查；`InMemoryTextSearchStore`
  在任何环境下都能使用。
- **维护需要显式进行。** `optimize()` 合并索引的段。当索引与已存储的文档不一致时（例如文件
  被其他工具编辑过之后），`integrity_check()` 返回 `False`，而 `rebuild_index()` 会根据
  已存储的文本修复索引，无需重新获取任何内容。由更新版本的库创建的文件会抛出
  `SearchStoreError`，而不会被使用。
- **自定义存储**继承 `AsyncTextSearchStore`；参见
  [添加新组件](../../project/contributing.md#adding-a-new-component)。
