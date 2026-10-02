# 运行语义

`AsyncETLPipeline.run` 提供以下保证。每条保证都有编号，并且在
`tests/semantics/test_run_rules.py` 中都有一个以规则编号开头的测试，例如
`test_r1_cursor_waits_for_settled_page`。修改一条规则属于破坏性变更：它会改变该规则的测试，
并在 [MIGRATION.md](../project/migration.md) 中添加一条记录。

当一条记录已被处理、被标记为不相关或作为被隔离的记录跳过时，它即为**已落定**（settled）。
当导出器已持久保存一条记录的实体时，该记录即为**已持久化**（durable）（R20）。当某页上有记录
失败且没有任何记录被处理，或者该页的导出器 `flush` 失败时，该页即为**停滞**（stalled）。
当某页没有下一个游标、没有条目或被截断时，该页即**结束列表**。

| 规则 | 保证 | 测试 | 源代码 |
|------|------|------|--------|
| R1 | 保存的游标永远不会越过含有未落定记录的页面向前移动：一旦有记录失败、因 `total_limit` 被推迟，或已写入但因 `flush` 失败而未持久化，游标就会在本次运行的剩余时间里停留在该页的开头。把游标重置到第一页（R15、R16）不算向前移动。作为被隔离的记录跳过的记录算作已落定（R18）。 | `test_r1_*` | `_listing_position.py:46-57` |
| R2 | `total_limit` 是精确的。相关记录在获取全文之前预留一个名额，失败的记录会把名额让给其他记录。 | `test_r2_*` | `pipeline_async.py:81-98`、`:802-821` |
| R3 | 不相关的记录会立即被标记为已处理，不获取其全文。 | `test_r3_*` | `pipeline_async.py:805-807` |
| R4 | `MEMORY_FAULTS` 中的记忆摄取异常会被记录到日志并计入 `RunMetrics.memory_faults`，该记录的实体仍会被导出。 | `test_r4_*` | `pipeline_async.py:832-840` |
| R5 | 两个停滞页之间如果没有任何处理过记录的页面，运行就会以 `PipelineAborted` 中止。单个停滞页是被容忍的。作为已处理或被隔离而跳过的记录，既不会使页面停滞，也不算处理了记录。导出器 `flush` 失败的页面属于停滞页（R21）。 | `test_r5_*` | `pipeline_async.py:46`、`:562-574` |
| R6 | 结束列表的停滞页，或者其后紧跟一个结束列表页面的停滞页，会在保存结尾之前中止运行。此规则优先于 R15。 | `test_r6_*` | `pipeline_async.py:575-576` |
| R7 | 没有下一个游标或没有条目的页面，在该页落定后以 `"completed"` 结束运行。此时 `OffsetListing` 会把偏移量保存到最后一个条目之后，因此之后追加的条目会被下一次运行找到；其他任何提取器都不保存游标，因此下一次运行从第一页开始。 | `test_r7_*` | `_listing_position.py:46-75` |
| R8 | 全部由已处理记录组成的页面不算结尾；分页会越过它继续。 | `test_r8_*` | `pipeline_async.py:601-613` |
| R9 | 关闭请求会完成正在处理的记录、刷新导出器、标记刷新后已持久化的记录、把该页的其余部分留给下一次运行、使保存的游标停留在该页之前、关闭导出器、写回状态，并抛出 `PipelineInterrupted`。 | `test_r9_*` | `pipeline_async.py:515-531`、`:767-785`、`:803-804` |
| R10 | 无论运行如何结束，都会先刷新并关闭导出器，然后写回状态。运行失败后其中任一步骤出现的故障会被记录到日志，因此绝不会掩盖原始错误；运行成功后导出器关闭时的故障，会在状态写回之后抛出。 | `test_r10_*` | `pipeline_async.py:451-469`、`:698-724` |
| R11 | `record_id` 缺失或为空的记录会被跳过、记录到日志，并以结果为 `"skipped"` 的 `RecordFinished` 事件报告。 | `test_r11_*` | `pipeline_async.py:740-745` |
| R12 | `sleep_between` 在页面之间等待，但永远不会在达到 `total_limit` 或结束列表的那一页之后等待。 | `test_r12_*` | `pipeline_async.py:582-587` |
| R13 | 无法获取或解析的列表页会以携带已处理记录数的 `PipelineAborted` 中止运行。 | `test_r13_*` | `pipeline_async.py:726-734` |
| R14 | 对于 `OffsetListing`，`newest_first=True` 的运行会从偏移量 0 开始翻页，直到找到保存在列表头部的记录，然后从保存的偏移量（按新条目数向后移动）继续。每个偏移量游标都来自 `cursor_for_offset`，列出的 id 来自页面中的记录，因此每一页只获取和解析一次。 | `test_r14_*` | `_listing_position.py:77-134` |
| R15 | 不属于停滞页的截断页会以 `"completed"` 结束运行，在 `RunMetrics.listing_truncated`、`PageFetched.truncated` 以及每次运行一条的日志中报告截断，即使有页面未落定也把保存的游标重置到第一页，并设置 `PipelineMetadata.truncated`。该标志由第一次在没有上限的情况下到达列表末尾的运行清除；中止、被中断或达到 `total_limit` 的运行不会改变它。 | `test_r15_*` | `pipeline_async.py:544-548`、`:578-581` |
| R16 | `StaleCursorError` 在每次运行中会让列表从第一页重新开始一次；同一次运行中第二次出现则抛出 `PipelineAborted`。 | `test_r16_*` | `pipeline_async.py:520-529` |
| R17 | 与不是 `OffsetListing` 的提取器一起使用 `newest_first=True` 或大于 0 的 `start_index`，会在任何请求之前抛出 `ValueError`。 | `test_r17_*` | `pipeline_async.py:443-446` |
| R18 | 设置了 `max_attempts` 时，只有来自处理过记录的页面，或来自之后在同一次运行中被其他页面解除停滞的停滞页的失败，才会通过 `record_failure` 计数；由始终未被解除的停滞页持有的失败会被丢弃。已计数尝试次数达到 `max_attempts` 的列表记录会作为被隔离的记录跳过，每次运行在 `RunMetrics.quarantined` 中计数一次，并只记录一次日志。在最后一次尝试失败的那次运行中，不会有记录被隔离。 | `test_r18_*` | `pipeline_async.py:124-141`、`:564-567`、`:601-631` |
| R19 | 只有得到答案，记录才会落定。用 `default_on_error=False` 构建的过滤器出现相关性故障，以及 LLM 响应中没有实体列表（因为回复为空，或有多个键但都不是 `result_key`），都会使记录失败：它保持未标记状态，其尝试按 R18 计数，并在下一次运行时重试。 | `test_r19_*` | `llm/openai_compatible_async.py:206-207`、`llm/extraction_async.py:281-288`、`llm/relevance_async.py:96-109`、`pipeline_async.py:802-821` |
| R20 | 只有当记录的实体已持久化时，它才会被标记为已处理：对于 `durable_writes = True` 的导出器是在 `write` 之后立即标记，否则是在该页 `flush` 之后标记。在 `write` 与 `flush` 之间崩溃，会在下一次运行中重复处理该记录，但不会丢失任何记录。 | `test_r20_*` | `pipeline_async.py:767-785`、`:814-817` |
| R21 | `write` 故障会使该记录失败，并按 R18 计一次尝试。`flush` 故障会使自上次成功刷新以来写入的记录保持未落定，不对它们计任何尝试，并使该页成为停滞页，因此连续两次刷新失败会按 R5 中止运行。 | `test_r21_*` | `pipeline_async.py:773-781`、`:814` |
| R22 | 导出器 `open` 中的故障会在任何列表请求之前以 `PipelineAborted` 中止运行。 | `test_r22_*` | `pipeline_async.py:453-457`、`:704-708` |
| R23 | 每条已处理的记录都会写入导出器，包括没有实体的记录；不相关的记录则不会。 | `test_r23_*` | `pipeline_async.py:805-814` |

源代码一列引用了每条规则背后的代码。移动了这些代码的变更也要更新此处的引用。

## 有上限的列表 {#capped-listings}

PubMed 只提供查询的前 9,999 条结果，Semantic Scholar 的相关性检索只提供前 1,000 条。它们的
提取器会把达到上限的那一页标记为截断，并适用 R15：本次运行正常完成，下一次运行会重新翻阅
可访问的结果。已处理的记录按 id 跳过，因此重新扫描只消耗列表请求，不消耗 LLM 调用：在
`page_size=100` 时，Semantic Scholar 最多 10 次请求，PubMed 最多 100 次。重新扫描还能找到
自上次运行以来进入可访问窗口的记录，这对按相关性排序的列表很重要。要避免重新扫描，请缩小
查询范围，例如按日期范围。OpenAlex 没有上限：`AsyncOpenAlexExtractor` 使用 OpenAlex 的
游标分页。
