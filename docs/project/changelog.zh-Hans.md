# 更新日志

sci-etl-core 的所有重要变更都记录在这里。格式遵循
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，版本号遵循
[语义化版本](https://semver.org/)。在 1.0 之前，次版本可能会改变行为；每项此类
变更都列在**变更**之下。


## [0.6.0] - 2026-09-27 {#060-2026-09-27}

本版本改变了数据契约：实体提取器可以返回类型化实体，导出器接收每条记录及其实体，本库通过
标准 `logging` 模块输出日志，基础安装只需要 Pydantic。它还新增了带有证据和溯源信息的论断。
请参阅 MIGRATION.md 中的“升级到 0.6”。

### 新增 {#added}

- **导出器生命周期。** `AsyncExporter` 具有 `open()`、`write(record, entities)`、`flush()`
  和 `aclose()`，`durable_writes` 说明是由 `write` 还是 `flush` 使实体持久化。流水线只有在
  记录的实体已持久化时才会将其标记为已处理，因此崩溃可能导致记录被重复处理，但绝不会丢失。
- `AsyncCsvExporter`：每个实体写一行，带有其论文的 `record_id`，把其他所有键保存在 `extra`
  列中，从不合并、截断或转换任何值。它每次运行根据一个只追加的日志生成一次文件，因此导出时间
  随记录数线性增长。电子表格会当作公式执行的单元格会被加上前导撇号；`-5.361` 这样的普通数字
  原样写入。
- `AsyncJsonlExporter`：每条记录追加一行 JSON；以及 `read_jsonl_export`：读回每条记录的最后
  一行。
- **类型化实体。** `AsyncLLMEntityExtractor(schema=Model)` 按 Pydantic 模型校验每个实体并
  返回模型实例。它通过新增的 `AsyncLLMClient.complete_structured` 请求 JSON Schema 结构化
  输出，对于支持该功能的端点，可由 `AsyncOpenAICompatibleClient(structured_output=True)` 和
  `LLMConfig.structured_output` 开启。`entity_list_schema` 用于构建所请求的模式。
- **拒绝原因。** `RecordValidator.validate` 返回一个由 `Violation` 组成的
  `ValidationResult`，指出每次拒绝的字段和规则。内置校验器会报告各自的规则，
  `CompositeValidator.validate` 会汇集每个校验器的违规项。拒绝会连同原因记录到日志。
- `AsyncEntityExtractor.extract_record(record, text)` 和 `requires_record`，用于需要记录本身
  的提取器。流水线调用的是 `extract_record`。
- `AsyncLLMEntityExtractor.prepare` 返回发送给模型的文本，`stamp` 描述其实体背后的模型、
  提示词、模式和库版本。`rejections=` 会把被拒绝的实体保存在拒绝记录存储中。
- `response_cache_key(schema=, variant=)` 和 `CachingLLMClient(variant=)`。类型化请求的模式
  会加入缓存键。
- `sci_etl_core.claims`（临时性）：`Claim`、`ClaimDraft`、`EvidenceSpan`、
  `ExtractionStamp`、`locate_quote`、`AsyncLLMClaimExtractor`，论断存储
  `InMemoryClaimStore` 和 `AsyncSqliteClaimStore`，`AsyncClaimStoreExporter`，以及拒绝记录
  存储 `InMemoryRejectionStore` 和 `AsyncSqliteRejectionStore`。
- `DeduplicationStep(source_column=)` 会添加一个 `sources` 列，列出合并进每个输出行的所有行
  的不同来源，例如每篇论文的 `record_id`。
- `ExportError`、`ClaimError` 和 `ClaimStoreError`。
- `config`、`arxiv`、`xml`、`html` 和 `processors` extra。
- `load_config(load_env=True)` 和 `load_config_async(load_env=True)`。

### 变更 {#changed}

- **破坏性变更：** 导出器在构造时接收目标位置，并实现 `write(record, entities)` 而不是
  `export(data, destination)`。流水线不再接受 `destination`。
- **破坏性变更：** 流水线会把每条已处理的记录（包括没有实体的记录）写入导出器，以便导出器
  清除重新提取后不再出现的行。
- **破坏性变更：** 流水线在第一次列表请求之前打开导出器，在每页之后刷新它，并且无论运行如何
  结束，都会在写回状态之前刷新并关闭它。`open` 故障会中止运行；`flush` 故障会使该页的记录
  保持未落定，且不对它们计入尝试。
- **破坏性变更：** 基础安装只依赖 `pydantic`。使用 `load_config` 需安装 `config` extra，
  使用 `AsyncArxivExtractor` 需安装 `arxiv`，使用 PubMed 提取器以及 JATS 和 DOCX 解析器需
  安装 `xml`，使用 `HtmlTextParser` 需安装 `html`，使用 pandas 处理器和表格输出端需安装
  `processors`。
- **破坏性变更：** 只有在传入 `env_path` 或 `load_env=True` 时，`load_config` 和
  `load_config_async` 才会读取 `.env` 文件。
- **破坏性变更：** 每个模块都通过 `logging.getLogger(__name__)` 在 `sci_etl_core` 记录器之下
  输出日志：失败和跳过的记录用 `WARNING`，输出端和状态故障用 `ERROR`，例行说明用 `INFO`。
  本库不配置任何处理器。
- **破坏性变更：** `AsyncEntityExtractor` 和 `AsyncExporter` 在实体类型上是泛型的，
  `AsyncLLMEntityExtractor` 中 `system_prompt` 之后的所有参数都只能以关键字形式传入。
- `AsyncLLMClient.invalidate` 为类型化请求接受 `schema=`。
- `async` extra 不再安装 `aiofiles`，`sql` extra 不再安装 `aiosqlite`。
- `AsyncArxivExtractor` 遇到 `406` 响应时会重试，而不是让请求失败，因为 arXiv 会对有效请求
  间歇性地返回该状态码。

### 移除 {#removed}

- 阻塞式接口 `Extractor`、`StateManager`、`Exporter`、`LLMClient`、`RelevanceFilter` 和
  `EntityExtractor`，以及 `Sync*Adapter` 类。
- `LegacyExtractorAdapter`。
- `AsyncExporter.export` 和流水线的 `destination` 参数。
- `AsyncCsvUpsertExporter`；请使用 `AsyncCsvExporter`。
- `AsyncSqlTableExporter` 和 `AsyncPlotly3DExporter`；请使用 `SqlTableSink` 和
  `Plotly3DSink`。`ScatterPlotConfig` 从 `sci_etl_core.processors` 导入。
- 所有 `logger=` 参数、`configure_logging` 以及 `AsyncETLPipeline.log`。

## [0.5.1] - 2026-09-26 {#051-2026-09-26}

本版本不再让没有实际回答的 LLM 响应使记录落定，防止 LLM 缓存重放这些响应，并增加了下载和
解压大小限制。升级后的第一次运行会让 LLM 缓存未命中一次。请参阅 MIGRATION.md 中的“升级到
0.5.1”。

### 新增 {#added_1}

- `AsyncLLMClient.invalidate(system_prompt, user_content)` 报告被拒绝的响应，
  `AsyncLLMResponseCache.delete(key)` 删除一个条目；两种内置缓存都实现了它。
- **大小限制。** `AsyncArxivExtractor`、`AsyncOpenAlexExtractor`、`AsyncPubMedExtractor` 和
  `AsyncSemanticScholarExtractor` 上的 `max_download_bytes` 会在解码后限制每个响应体的大小，
  `LatexTarballParser(max_tex_bytes=)` 会限制从一个 e-print 中解压出的 TeX。过大的列表页会
  抛出 `ExtractionError`；过大的全文下载或 e-print 会被记录并跳过。两者默认都不限制。
- `AsyncArxivExtractor.from_config(full_text=)` 根据 `full_text` 配置部分构建提取器的速率
  限制器。
- `AsyncOpenAICompatibleClient` 和 `CachingLLMClient` 提供 `base_url` 和 `temperature`，每个
  `AsyncLLMClient` 都提供 `response_format`，默认为 `{"type": "json_object"}`。
  `response_cache_key` 以关键字形式接受这三者。

### 变更 {#changed_1}

- 空的 LLM 回复现在会使记录失败，而不是使其落定。`AsyncOpenAICompatibleClient.complete_json`
  在过去返回 `{}` 的地方抛出 `LLMError`，因此流水线会在下一次运行时重试该记录，而不是在什么
  都没导出的情况下把它标记为已处理。
- 当响应中没有实体列表（为空，或有多个键但都不是 `result_key`）时，
  `AsyncLLMEntityExtractor.extract` 会抛出 `LLMError`。过去它返回 `[]`，记录会被标记为已
  处理。
- 设置了 `default_on_error=False` 的 `AsyncLLMRelevanceFilter` 和
  `AsyncEmbeddingRelevanceFilter` 在出错时会关闭：调用失败或结论不明确都会抛出异常，该记录会
  在下一次运行时重试。过去这会被解读为不相关，记录会被永久标记为已处理。
- LLM 缓存键现在包含端点的 `base_url`、温度和响应格式，因此为某个服务商、温度或格式缓存的
  回答不再会提供给另一个。早期版本缓存的响应不会被找到，升级后的第一次运行会为每个请求调用
  LLM。
- 没有 `delete` 的第三方 `AsyncLLMResponseCache` 会继续提供本库拒绝的响应。请实现
  `delete`，或者接受重放。
- `PdfPlumberParser.extract_text` 只打开一次 PDF 即可读取文本和表格，过去会打开两次。
- 重复调用时，`AsyncSqliteEmbeddingStore.query` 快得多。该存储把向量保存在内存中，只有在文件
  发生变化后才重新读取，用一次 NumPy 乘积为它们打分，并且只为返回的文本块读取文本和元数据。
  在含 9,000 个文本块的记忆上构建发现图的速度提高了约四倍。现在该存储在两次查询之间会把向量
  保存在内存中，直到被关闭。
- 发布不再等待 sci-etl-cli 和 udg-catalogue 在新版本上运行；使用方的就绪情况改为在发布说明中
  报告。

### 修复 {#fixed}

- `AsyncArxivExtractor` 会像其他内置提取器一样重试 `408` 请求超时。它现在与它们共用重试代码，
  因此其重试和失败消息以 `arXiv` 开头并指明操作，例如
  `arXiv LaTeX fetch for '2401.00001v1' failed after 3 attempts`。
- 当 SQLite 无法高亮位于 `OR` 或 `NOT` 内部、带字段限定的 `NEAR` 分组时（SQLite 3.50.4 对
  部分文档就是如此），`AsyncSqliteFts5Store.search` 会抛出注明 SQLite 版本的
  `SearchQueryError`。过去它抛出带有 “database disk image is malformed” 的
  `SearchStoreError`，看起来像是索引已损坏。
- `CachingLLMClient` 不再重放被实体提取器或相关性过滤器拒绝的响应。过去被拒绝的响应会被缓存，
  因此每次重试都会得到同样的回答，直到该记录被隔离，而模型从未被再次询问。

## [0.5.0] - 2026-09-25 {#050-2026-09-25}

本版本改变了提取器翻阅列表的方式、保存的运行状态以及流水线的构造方式。0.4 保存的状态会被
自动升级。代码层面的改动请参阅 MIGRATION.md 中的“升级到 0.5”。

### 新增 {#added_2}

- **游标分页。** 提取器从 `fetch_page` 返回一个 `ListingPage`，其中带有下一页的游标。按偏移量
  分页的提取器还实现了 `OffsetListing`，这是 `newest_first` 运行和 `run(start_index=)` 所
  需要的。
- **对持续失败的记录进行隔离。** `run(max_attempts=3)` 会跳过在 3 次运行中都失败的记录。
  `RunMetrics.quarantined` 统计被跳过的记录。两种内置状态管理器都会存储每条记录的尝试次数和
  最后一次错误。
- **报告结果上限。** `RunMetrics.listing_truncated`、`PageFetched.truncated` 和
  `PipelineMetadata.truncated` 会显示来源何时在其结果上限处停止。进度事件还包含页面的
  `cursor`。
- **表格输出端。** `sci_etl_core.processors.sinks` 中的 `SqlTableSink` 和 `Plotly3DSink` 用于
  写出后处理后的 `DataFrame`。
- **模式版本。** SQLite 状态数据库、LLM 缓存、嵌入存储以及文件状态都会记录模式版本。由更新
  版本写入的文件会被拒绝，对于状态文件会抛出 `StateStoreError`。
- `StaleCursorError`，用于来源不再接受的游标。
- `BaseAppConfig.strict_sections`，用于退出严格的配置校验。
- `LegacyExtractorAdapter`，可在为 0.4 编写的提取器完成移植之前运行它。它一推出即为弃用
  状态。

### 变更 {#changed_2}

- **破坏性变更：** `AsyncExtractor.fetch_page(query, cursor, page_size)` 取代了 `search` 和
  `parse_listing`。流水线现在会自行跳过已处理的记录。
- **破坏性变更：** `PipelineMetadata.cursor` 取代了 `last_start_index`。
- **破坏性变更：** 流水线构造函数以位置或名称接收五个协作组件，其他所有参数都只能以关键字
  形式传入。`run()` 中 `query` 之后的所有参数都只能以关键字形式传入。
- **破坏性变更：** `RawRecord`、`PipelineMetadata`、`TokenUsage`、`RunMetrics` 以及进度事件
  必须用关键字参数构造。
- **破坏性变更：** 本库配置部分中的未知键（例如 `search.bm25.titel`）会导致校验失败，而不再
  被忽略。
- **破坏性变更：** 需要 Python 3.11 或更高版本。
- 到达来源结果上限的运行现在会正常完成，下一次运行会重新从第一页开始，而不会停在上限处。
- 被来源拒绝的游标会让列表从第一页重新开始一次。
- `AsyncOpenAlexExtractor` 使用 OpenAlex 游标分页，不再局限于前 10,000 条结果。它不再支持
  `newest_first`。
- `AsyncPubMedExtractor` 和 `AsyncSemanticScholarExtractor` 会在结果的最后一页停止，而不会
  多发一次空请求。

### 弃用 {#deprecated}

以下内容在 0.5 中仍可使用，并将在 0.6.0 中移除。

已有替代品（`DeprecationWarning`）：

- 阻塞式接口 `Extractor`、`StateManager`、`Exporter`、`LLMClient`、`RelevanceFilter` 和
  `EntityExtractor`，以及 `Sync*Adapter` 类；
- `LegacyExtractorAdapter`；
- `AsyncSqlTableExporter` 和 `AsyncPlotly3DExporter`，由 `SqlTableSink` 和 `Plotly3DSink`
  取代。

替代品将在 0.6.0 中提供（`PendingDeprecationWarning`，因此目前无需任何修改）：

- `logger=` 参数和 `configure_logging`；
- `AsyncETLPipeline(destination=)`；
- `AsyncExporter.export` 和 `AsyncCsvUpsertExporter`。

### 移除 {#removed_1}

- 配置键 `pipeline.max_records` 和 `pipeline.max_workers`、对应的 `PipelineConfig` 属性以及
  `run(max_records=)`。请使用 `total_limit` 和 `max_concurrency`。
- `build_retrying_session`，以及 `full` extra 中的 `requests`。

### 修复 {#fixed_1}

- `AsyncPubMedExtractor` 不再请求第 9,999 条之后的结果，PubMed 会拒绝这类请求。

## [0.4.1] - 2026-09-25 {#041-2026-09-25}

### 变更 {#changed_3}

- `HttpConfig.user_agent` 和 `build_async_client` 默认使用
  `sci-etl-core/<installed version>`，而不是 `sci-etl-core/0.1`。

### 修复 {#fixed_2}

- `load_config_async` 和 `AsyncCsvUpsertExporter` 改为在工作线程中检查文件是否存在，而不再
  阻塞事件循环。
- `sql` 和 `full` extra 要求 `sqlalchemy[asyncio]`，因此会安装 `greenlet`。SQLAlchemy 2.1
  默认不再安装它，而没有它就无法导入 `AsyncSqlTableExporter`。

## [0.4.0] - 2026-09-16 {#040-2026-09-16}

### 新增 {#added_3}

- `AsyncPubMedExtractor`、`AsyncSemanticScholarExtractor` 和 `AsyncOpenAlexExtractor`。每个
  提取器都会在 `RawRecord.metadata` 中填写 `authors` 和 `categories`，在来源提供日期时还会
  填写 `published` 和 `year`，并在遇到传输故障、`408`、`429` 和服务器错误时重试，同时遵循
  `Retry-After`。`AsyncOpenAlexExtractor` 还会把论文引用的作品保存在 `references` 下。
- 用于 Word `.docx` 文件的 `DocxParser`，以及用于 JATS XML 的 `JatsXmlParser`，后者的
  `parse_article` 会返回一个包含章节、作者、关键词、标识符和参考文献的 `JatsArticle`。
- LLM 响应缓存：`CachingLLMClient` 可以包装任何 `AsyncLLMClient`，并从
  `AsyncLLMResponseCache`（`InMemoryLLMResponseCache` 或 `AsyncSqliteLLMResponseCache`）中
  回答重复的请求。缓存故障会被记录并计入 `CacheStats`，存储会将其作为 `LLMCacheError` 抛出，
  并且永远不会导致模型请求失败。
- 优雅关闭：`AsyncETLPipeline(shutdown=)` 和 `ETLPipeline(shutdown=)` 接受一个
  `ShutdownSignal`，因此 SIGINT、SIGTERM 或 `request()` 会让正在处理的记录完成，并抛出
  `PipelineAborted` 的子类 `PipelineInterrupted`。现在无论运行如何结束，最后都会调用状态
  管理器的 `flush()`。
- 进度事件和运行指标：`on_event` 接收来自 `sci_etl_core.observability` 的 `RunStarted`、
  `PageFetched`、`RecordFinished`、`PageFinished` 和 `RunFinished`，`last_run_metrics` 返回
  包含计数、耗时、运行结果以及 `usage_sources` 所用 token 的 `RunMetrics`。`TokenUsage` 支持
  `+` 和 `-`。
- `run(newest_first=True)` 无需从偏移量 0 重新扫描，即可获取最新优先列表中的新投稿。
  `PipelineMetadata` 新增了 `head_ids`、`head_offset` 和 `tail_ids`，两种状态后端都会保存
  它们。
- 每个内置提取器、`AsyncOpenAICompatibleClient` 和 `AsyncOpenAIEmbedder` 上的
  `rate_limiter`，以及用于按主机限制的 `HostRateLimiter`。
- 根据配置构建组件：`AsyncArxivExtractor.from_config`、
  `AsyncOpenAICompatibleClient.from_config`、`AsyncETLPipeline.from_config` 和
  `ETLPipeline.from_config`，以及 `HttpConfig.build_client()`、
  `RateLimitConfig.build_limiter()` 和 `PipelineConfig.run_arguments()`。`search` 配置部分
  用于构建 `BM25Weights`、`FusionParams`、`HybridParams` 和 `GraphParams`。`PipelineConfig`
  新增了 `newest_first`，`AsyncOpenAICompatibleClient` 新增了 `model` 属性。
- `AsyncLLMEntityExtractor(validator=, logger=, label_field=)` 会丢弃并记录被
  `RecordValidator` 拒绝的实体。
- `ScatterPlotConfig` 接受 `hover_data_columns`、`hover_template`、
  `color_continuous_scale`、`color_range`、`color_label`、`marker` 和 `layout`。
- `ValueClipStep` 在后处理期间截断数值列，`TableLayoutStep` 对行排序并调整列顺序。
- 查询语言中的 `NEAR(...)` 邻近查询，表现为带 `NEAR_DISTANCE` 的 `Near` 节点，两种文本存储
  都支持；以及 `QueryChip.near`。
- 范围过滤器：`RangeFilter` 在两种文本存储、混合检索和 `filter_graph` 中，保留标签位于整数或
  文本边界（例如年份或 ISO 8601 日期）之间的记录。`AsyncTextSearchStore.range_counts` 统计
  多个范围中各自的匹配数。`SearchFilter` 表示这两种过滤器类型中的任一种。
- 更丰富的摘要片段：`TextHit.snippets` 和 `FusedHit.snippets` 为每个有高亮匹配的字段保存一个
  `Snippet`。`passage_snippet` 和 `snippet_window` 可为其他文本构建摘要片段。
- `backfill_text_index` 根据向量记忆中的文本块构建文本索引，去除相互重叠的文本块所共有的词
  （`merge_passages`），并在 `BackfillReport` 中报告所做的工作。
  `AsyncEmbeddingStore.iter_records` 以 `StoredRecord` 的形式逐条产出每条记录的段落，不加载
  向量，两种内置存储都实现了它。
- `AsyncSimilarArticleFinder.find_best_chunks` 返回每篇文章最好的文本块（包含文本）。
  `SlidingWindowChunker` 提供 `chunk_words` 和 `overlap_words`。

### 变更 {#changed_4}

- `PipelineConfig.max_records` 现在是 `total_limit`，`max_workers` 现在是
  `max_concurrency`。旧的 YAML 键和属性在 0.5.0 之前仍可使用并发出 `DeprecationWarning`；
  如果加载的配置把旧键和新键设为不同的值，会抛出 `ConfigurationError`。`run(max_records=)` 也
  以同样方式弃用。
- `build_retrying_session` 已弃用，将在 0.5.0 中与 `full` extra 中的 `requests` 一起移除。
- 仅由语义分支找到的混合检索命中结果，现在会在 `snippet`、`highlights` 和 `snippets` 中带有其
  最佳文本块的摘要片段，过去这些字段是空的。过去在 `snippet` 为空时显示摘要的代码，应改为检查
  `lexical_rank is None`。
- `ETLPipeline.run` 以较短的时间片等待后台循环，因此调用线程上的信号处理器能及时运行，
  `KeyboardInterrupt` 会取消后台循环上的运行。

## [0.3.0] - 2026-09-15 {#030-2026-09-15}

### 新增 {#added_4}

- `sci_etl_core.search` 中的本地布尔检索，只需要标准库：
  - 一种查询语言，支持词项、`"短语"`、`prefix*` 前缀词项、`title:`、`abstract:` 和 `body:`
    字段限定、`AND`、`OR` 和 `NOT`（也可写作 `&&`、`||`、`-`，`AND` 还可以什么都不写）以及
    括号。`parse_query` 返回规范化的 AST，格式错误的查询会抛出 `SearchQueryError`，其
    `position` 和 `token` 指出错误位置。`describe` 把查询转换为用于显示的标签。
  - `AsyncSqliteFts5Store`，基于 SQLite FTS5 的持久化文本索引。它按带有逐字段
    `BM25Weights` 的 BM25 排序，返回带高亮偏移量的纯文本摘要片段，按元数据过滤
    （`MetadataFilter`），在其 `facet_keys` 上统计分面，并提供 `optimize`、`rebuild_index`、
    `rebuild_tags` 和 `integrity_check` 用于维护。`fts5_available()` 报告解释器的 SQLite 是否
    包含 FTS5。
  - `InMemoryTextSearchStore`，匹配的记录与 FTS5 存储相同。
  - `AsyncSearchIndexer`，即 `AsyncChunkIngestor` 在文本索引方面的对应物。
  - 排名融合：使用默认的 `reciprocal_rank_fusion` 或 `normalized_score_fusion`，通过
    `FusionParams` 配置。
  - `AsyncHybridSearcher`，运行词法、语义或混合检索，并在 `SearchOutcome.degraded` 和
    `SearchOutcome.skipped` 中报告哪些检索分支失败或没有可运行的内容。
- `sci_etl_core.search` 中的发现图。`build_discovery_graph` 从一个或多个边来源出发，以广度
  优先方式生长种子记录的邻域，默认只保留互为最近邻的记录，并通过确定性的标签传播把记录分组为
  社区。`GraphParams` 限制深度、扇出、最小边权重、节点数和标签传播轮数，
  `DiscoveryGraph.communities_converged` 报告轮数上限是否提前截断了标签传播。`filter_graph`
  无需任何 I/O，即可把已构建的图缩小到匹配的记录和元数据过滤条件。`label_communities` 和
  `select_edges` 也是公开的。
- 位于新接口 `AsyncEdgeSource` 之后的边来源。`EmbeddingEdgeSource` 按向量记忆中的余弦相似度
  关联记录，`MetadataEdgeSource` 按两条记录共有标签（例如 arXiv 分类和作者）的比例关联记录。
- `sci_etl_core.discovery`，供用户界面使用的读模型：`Facet` 和 `DiscoveryResult`，也从
  `sci_etl_core` 导出。导入它不会加载任何存储或可选依赖。
- `AsyncCompositeIngestor`，把每条记录同时发送到多个记忆后端（例如向量记忆和文本索引），这样
  其中一个出现记忆故障时不会让其他后端停止。
- `MemoryIngestor`，即 `memory_ingestor` 需满足的协议；以及 `MEMORY_FAULTS`，即流水线视为记忆
  故障的异常。
- `SearchError` 及其子类 `SearchQueryError` 和 `SearchStoreError`。
- `search` extra。它不安装任何东西，因为检索只需要标准库；它让依赖文件可以说明为什么需要这个
  包。

### 变更 {#changed_5}

- `AsyncETLPipeline(memory_ingestor=)` 接受任何 `MemoryIngestor`。记忆摄取期间的
  `SearchStoreError` 会被记录，该记录的实体仍会被导出，与嵌入故障的处理方式相同。
  `SearchQueryError` 不属于记忆故障，会导致该记录失败。
- arXiv 记录的 `RawRecord.metadata` 不再为空：`AsyncArxivExtractor` 会在其中填写
  `categories`、`authors`、`published` 和 `year`。比较 `metadata == {}` 的代码会注意到这一
  变化。`AsyncChunkIngestor` 存储的文本块元数据保持不变。
- `AsyncSqliteEmbeddingStore` 运行在一个共享的内部 SQLite 执行器上。这不改变行为：异常类型、
  消息、事务以及取消时的行为都保持不变。

### 修复 {#fixed_3}

- `AsyncSqliteStateManager`：取消正在等待状态操作的任务时，不再在其工作线程仍在使用连接时
  释放该连接。下一个操作会等待该线程结束。

## [0.2.0] - 2026-09-14 {#020-2026-09-14}

### 安全 {#security}

- `load_config` 和 `load_config_async` 不再把 pydantic 的错误文本复制到
  `ConfigurationError` 中。该文本可能包含原始设置，进而包含从环境中读取的 API 密钥。消息现在
  会列出每个出错的键及原因，但不包含其值，校验错误也不再与之链接。

### 新增 {#added_5}

- `validate_config(config_cls, raw, source)` 使用同样不泄露机密的消息，校验以其他方式加载的
  设置。
- `Retry-After` 支持。当被限流或失败的响应通过 `Retry-After` 或 OpenAI 兼容 API 发送的
  `retry-after-ms` 头要求的等待时间比退避时间更长时，`AsyncArxivExtractor`、
  `AsyncOpenAICompatibleClient` 和 `AsyncOpenAIEmbedder` 会按其要求等待。新增的
  `max_retry_after` 参数用于限制等待时间（默认 60 秒）。
- arXiv 提取器会记录每次重试及其等待时间。
- Token 用量。`AsyncOpenAICompatibleClient.usage` 和 `AsyncOpenAIEmbedder.usage` 返回一个
  `TokenUsage` 快照，包含 `requests`、`prompt_tokens`、`completion_tokens` 和
  `total_tokens`。`AsyncLLMClient` 和 `AsyncEmbedder` 上的 `usage` 属性除非被重写，否则返回
  `None`。
- ruff 和 mypy 在 CI 中运行，`lint` extra 用于在本地安装它们。
- 本更新日志。

### 变更 {#changed_6}

- 聊天和嵌入客户端中关闭了 OpenAI SDK 内置的重试，因此 `max_retries` 现在就是总尝试次数。过去
  SDK 可能会自行把每次尝试再重试一遍。
- 无效设置的消息以 `Invalid configuration in <file>:` 开头，每个问题单独占一行。
- `AsyncETLPipeline.__aexit__` 被标注为返回 `None`，因此类型检查器知道 `async with pipeline`
  永远不会抑制异常。

## [0.1.2] - 2026-09-14 {#012-2026-09-14}

### 修复 {#fixed_4}

- `max_concurrency` 为 0 时，每条记录都会永远等待。现在小于 1 的值会抛出 `ValueError`，小于 1
  的 `page_size` 和负数 `total_limit` 也是如此。
- 在其余记录都不相关的页面上，只要有一条记录失败，就会中止整个运行。现在，只有当第二个页面在
  取得任何进展之前就失败且没有处理任何记录，或者列表在这样的页面之后立即结束时，运行才会中止。
- 流水线在达到 `total_limit` 之后还会多等待一次 `sleep_between`。
- `max_retries` 小于 1 时，arXiv 提取器、LLM 客户端和嵌入器会在一次都不尝试的情况下失败。现在
  会抛出 `ValueError`。
- 日志文件所在文件夹不存在时，`configure_logging` 会失败，并且在之后的调用中会忽略不同的文件
  或级别。
- `AsyncFileStateManager` 会悄悄去掉记录 id 中的空白，导致这类记录在每次运行中都被重新处理。
  现在它会拒绝这类 id，流水线会跳过空 id。
- `last_run_at` 以带偏移量的 UTC 时间记录，而不再使用不带时区的本地时间。

### 新增 {#added_6}

- `PipelineConfig.page_size` 和 `PipelineConfig.search_delay`。
- 对每个配置部分进行范围校验。

### 变更 {#changed_7}

- 发布工作流会把构建产物上传到已存在的 GitHub 发布，而不是失败。

## [0.1.1] - 2026-09-14 {#011-2026-09-14}

### 新增 {#added_7}

- 由标签触发的发布工作流：运行 CI 测试套件，核对标签与项目版本是否一致，并通过可信发布发布到
  PyPI。
- 用于 PyPI 的包元数据：许可证、关键词、分类器和项目 URL。

## [0.1.0] - 2026-09-13 {#010-2026-09-13}

第一个打了标签的版本：异步流水线及其阻塞式外观、arXiv 提取器、OpenAI 兼容的聊天和嵌入客户端、
PDF、LaTeX 和 HTML 解析器、CSV、SQL 和 Plotly 导出器、数据框处理器和校验器、文件和 SQLite
状态、语义记忆，以及 udg-catalogue 迁移指南。

[Unreleased]: https://github.com/xueromll/sci-etl-core/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/xueromll/sci-etl-core/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/xueromll/sci-etl-core/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/xueromll/sci-etl-core/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xueromll/sci-etl-core/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xueromll/sci-etl-core/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xueromll/sci-etl-core/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/xueromll/sci-etl-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/xueromll/sci-etl-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xueromll/sci-etl-core/releases/tag/v0.1.0
