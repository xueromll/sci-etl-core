# 状态、续跑与错误

## 状态后端 {#state-backends}

本库附带两种状态后端：

- **`AsyncFileStateManager(processed_ids_file, metadata_file)`** 每行存储一个已处理的 id，
  另有一个 JSON 元数据文件。它持有操作系统级别的文件锁，并以原子方式写入元数据。
- **`AsyncSqliteStateManager(database_path)`** 使用 WAL 模式的 SQLite 数据库。请把它加入
  `closeables`，以便关闭其连接。它的 `flush()` 会为 WAL 做检查点。

两者都会记录模式版本：SQLite 数据库记录在 `PRAGMA user_version` 中，元数据文件记录在
`schema_version` 键中。两者都能读取 sci-etl-core 0.4 写入的文件（其中保存的偏移量会变成
游标）；对于由更新版本写入的文件，则抛出 `StateStoreError`，而不会读取或覆盖它。自定义的
`AsyncStateManager` 需要实现四个抽象方法；`record_failure`、`failure_counts` 和 `flush`
都有默认实现。

## 续跑 {#resuming}

每次运行都从保存的 `cursor` 开始，并跳过已经处理过的 id。游标在每一页之后保存，但只有当
页上的每条记录都已落定（即已处理、被标记为不相关或作为被隔离的记录跳过）时，游标才会越过该
页。当有记录失败，或因达到 `total_limit` 而被遗留时，游标会在本次运行的剩余时间里停留在该页
的开头，因此下一次运行会重新访问该页，同时跳过所有已处理的内容。当一次运行到达列表末尾时，
按偏移量分页的提取器会把偏移量保存到最后一个条目之后，其他任何提取器都不保存游标，因此下一次
运行从第一页开始。[运行语义](run-semantics.md)列出了运行遵循的每条规则，以及检查每条规则的
测试。

只有当导出器已持久保存某条记录的实体时，该记录才会被标记为已处理：对于
`durable_writes = True` 的导出器是在 `write` 之后立即标记，否则是在该页 `flush` 之后标记。
在两者之间崩溃会让该记录在下一次运行中被重复处理，但永远不会丢失。内置导出器在记录再次写入
时会替换其先前的输出，因此重复处理无害；你自己的导出器也必须以同样的方式保持幂等。

当状态文件存在但无法读取时，`AsyncFileStateManager` 会抛出 `OSError`，而不会把它当作空
文件。它会拒绝包含换行或首尾带有空白的记录 id，因为这两种 id 都无法原样读回。无效的元数据
内容会退回到第一页，代价只是一次重新扫描。两种后端都会以 UTC 时区的 ISO 8601 时间戳记录
`last_run_at`。

## 持续失败的记录 {#records-that-keep-failing}

每次运行都失败的记录（例如 PDF 会让解析器崩溃的论文）否则会被无限重试，并把保存的游标卡在
它所在的页面。默认的 `run(max_attempts=3)` 会通过状态管理器统计每次失败的尝试，并从下一次
运行开始，把尝试次数达到 `max_attempts` 的记录作为被隔离的记录跳过。被隔离的记录不会被处理
或重试，对于保存的游标而言算作已落定，计入 `RunMetrics.quarantined`，并且每次运行只记录一次
日志。两种内置状态管理器都会存储每条记录的尝试次数和最后一次错误（截断到 4,096 个字符），
而把记录标记为已处理会清除这些信息。

只有来自处理过记录的页面，或来自之后在同一次运行中被其他页面解除停滞的停滞页的尝试，才会被
计数。所有记录都失败的页面并不能说明这些记录本身有问题：在服务中断或 API 密钥被拒绝时，每条
记录都会失败，运行会中止（R5、R6），并且不会计入任何尝试。

这有一个局限。在没有其他相关记录的页面上失败的记录会使该页停滞。如果列表继续，之后处理了
记录的页面会解除停滞，这次尝试会被计数。如果那一页就是列表的最后一页，运行会中止且不计入
任何内容，因此这样的记录只有在列表越过它继续下去的运行中才会进入隔离状态。

传入 `max_attempts=None` 则不做任何计数，并在每次运行中重试每条失败的记录，与 0.4 的行为
相同。没有重写 `record_failure` 和 `failure_counts` 的自定义状态管理器永远不会隔离记录。

## 最新优先的列表 {#newest-first-listings}

arXiv 提取器先列出最新的投稿，PubMed 提取器默认也按最新优先排序，因此新论文会把旧论文推到
更大的偏移量处。从保存的偏移量续跑的运行会继续向更旧的论文推进，永远看不到新论文。传入
`newest_first=True` 即可兼顾两者：

```python
await pipeline.run(query="all:galaxy", total_limit=500, newest_first=True)
```

这样的运行会从偏移量 0 开始翻页，直到越过上一次运行在列表顶部看到的那些记录。这些记录移动的
距离就是新投稿的数量，因此保存的偏移量也向后移动了同样的数量。运行会跳到该偏移量之前的那一
页，并检查上次在那里看到的记录是否仍在页上。如果在，说明中间的论文已被之前的运行落定，不会
再次列出，翻页继续进行。

- **此模式下的第一次运行：** 还没有可查找的已保存内容，因此它会从偏移量 0 开始扫描，按 id
  跳过已处理的记录，并为下一次运行保存列表的头部。
- **顶部附近的失败：** 下一次运行要查找的头部取自有记录失败的那一页，因此那次运行至少会翻到
  那里并重新访问它。
- **条目被删除或重新排序：** 当保存的偏移量之前的记录不在应在的位置时，运行会从顶部继续翻页
  而不是跳过，并记录 `Records last seen before the saved offset have moved`。
- **保存的头部不再出现在列表中：** 运行会一直翻到列表末尾，相当于一次完整的重新扫描，并保存
  新的头部。

有新论文时，一次典型的运行需要在顶部发出两三次列表请求、一次检查保存偏移量的请求，以及处理
积压所需的请求。它所依赖的记录由两种状态后端以 `head_ids`、`head_offset` 和 `tail_ids` 的
形式保存在 `PipelineMetadata` 中。`newest_first` 需要按偏移量分页的提取器
（`OffsetListing`），并且不能与 `start_index` 一起使用。

不使用 `newest_first` 时，可以传入 `start_index=0` 从第一页重新扫描列表，例如顺序发生了变化
的列表：已处理的记录按 id 跳过，因此重新扫描只消耗列表请求（每次请求之前都有提取器的
`sleep_before_search` 延迟），而不会重新处理任何内容。

## 出现故障时会发生什么 {#what-happens-when-something-fails}

| 情况 | 行为 |
|------|------|
| 重试后列表请求仍然失败 | `run()` 抛出 `PipelineAborted`（原因：`UpstreamError`） |
| 来源拒绝列表请求，例如 arXiv 返回 `400` | `run()` 抛出 `PipelineAborted`（原因：`ExtractionError`） |
| 列表返回内容无法解析 | `run()` 抛出 `PipelineAborted`（原因：`MalformedResponseError`） |
| 列表有效但没有条目，或某页没有下一个游标 | `run()` 正常返回计数 |
| 来源在其结果上限处停止 | `run()` 正常返回计数；下一次运行从第一页开始 |
| 来源拒绝保存的游标（`StaleCursorError`） | 列表从第一页重新开始；同一次运行中第二次被拒绝则抛出 `PipelineAborted` |
| 列表页中只有已处理或被隔离的记录 | 继续翻到下一页 |
| 单条记录抛出异常，例如全文获取的临时故障 | 以警告记录；该记录保持未标记；保存的游标停留在其所在页；计入一次尝试；其他记录继续处理 |
| 导出器的 `write` 对某条记录抛出异常 | 同上：该记录失败，并计入一次尝试 |
| 导出器的 `flush` 抛出异常 | 以错误记录；本应由该次刷新持久化的记录保持未标记，不对它们计入尝试，该页算作停滞页 |
| 导出器的 `open` 抛出异常 | `run()` 在任何列表请求之前抛出 `PipelineAborted` |
| 某页上的记录失败且该页没有处理任何记录，但之后的页面处理了记录 | 继续翻页；失败的记录保持未标记，留给下一次运行 |
| 自上一个处理过记录的页面之后，第二个页面上又出现记录失败且没有任何记录被处理，或者在列表最后一页上出现这种情况，例如 API 密钥被拒绝或 CSV 无法读取 | `run()` 抛出 `PipelineAborted`（原因：最后一条记录的错误） |
| 通过 `shutdown` 请求关闭 | `run()` 抛出 `PipelineInterrupted`；参见[优雅关闭](shutdown.md) |
| arXiv 报告 LaTeX 和 PDF 都不可用（例如 404），或两者都无法解析 | 全文退回到摘要 |
| arXiv 把单个 gzip 压缩的 `.tex` 文件或 PDF 作为 e-print 提供 | 读取该 TeX，或改用该 PDF |
| `AsyncLLMRelevanceFilter` 内的 LLM 调用失败，或其结论不明确 | 返回 **`True`**；设置 `default_on_error=False` 时，`LLMError` 会向上传播：记录日志，该记录保持未标记，并在下一次运行时重试 |
| 记录的摘要为空 | 相关性过滤器返回 `default_on_empty_abstract`（**`True`**） |
| `AsyncLLMEntityExtractor` 内的 LLM 调用失败、回复为空、有多个键但都不是 `result_key`，或其实体列表格式错误 | `LLMError` 向上传播：记录日志，该记录保持未标记，并在下一次运行时重试 |
| 记录的 `record_id` 缺失或为空 | 跳过并记录日志，因为无法将其作为已处理记录来跟踪 |

## 异常 {#exceptions}

本库的所有异常都派生自 `SciEtlError`：`ExtractionError`（`UpstreamError`、
`MalformedResponseError`）、`ParsingError`、`LLMError`、`LLMCacheError`、
`EmbeddingError`、`EmbeddingStoreError`、`SearchError`（`SearchQueryError`、
`SearchStoreError`）、`StateStoreError`、`ConfigurationError` 以及 `PipelineAborted`
（`PipelineInterrupted`）。`ExtractionError` 还有 `StaleCursorError`。它们都可以从
`sci_etl_core` 导入。内置解析器遇到无法读取的字节时会抛出 `ParsingError`；自定义的 `Parser`
也应如此，这样 `AsyncArxivExtractor` 会转而尝试下一个来源，而不是让该记录失败。
