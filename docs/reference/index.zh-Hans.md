# API 参考

这些页面根据源代码中的文档字符串（docstring）和类型注解生成，因此类和函数的说明为英文。
每个页面记录定义这些名称的模块；请从页面开头注明的包中导入它们，而不要从定义它们的模块
导入，因为包内的模块布局可能在版本之间发生变化。

| 页面 | 包 | 内容 |
|------|----|------|
| [流水线](pipelines.md) | `sci_etl_core` | `AsyncETLPipeline`、`ETLPipeline`、记忆摄取、`ShutdownSignal`、进度事件和 `RunMetrics` |
| [配置](configuration.md) | `sci_etl_core` | `BaseAppConfig` 及其各个部分、`load_config`、`load_config_async` |
| [模型与异常](models.md) | `sci_etl_core` | `RawRecord`、`TokenUsage`、`SciEtlError` 异常层级、发现读模型 |
| [提取器](extractors.md) | `sci_etl_core.extractors` | `AsyncExtractor`，以及 arXiv、PubMed、Semantic Scholar 和 OpenAlex 提取器 |
| [解析器](parsers.md) | `sci_etl_core.parsers` | PDF、LaTeX、HTML、DOCX 和 JATS XML 解析器，参考文献裁剪 |
| [LLM](llm.md) | `sci_etl_core.llm` | LLM 客户端、响应缓存、相关性过滤器、实体提取器和类型化模式 |
| [嵌入](embeddings.md) | `sci_etl_core.embeddings` | 嵌入器、分块、向量存储、相似度检索 |
| [检索](search.md) | `sci_etl_core.search` | 查询语言、文本存储、融合、混合检索、发现图 |
| [导出器](exporters.md) | `sci_etl_core.exporters` | 导出器生命周期、CSV 和 JSON Lines 导出器 |
| [论断](claims.md) | `sci_etl_core.claims` | 论断、证据片段、标记、论断存储和拒绝记录存储、论断提取器和导出器（临时性 API） |
| [处理器](processors.md) | `sci_etl_core.processors` | DataFrame 步骤、键规范化器、记录校验器及其违规项、表格输出端 |
| [状态](state.md) | `sci_etl_core.state` | 文件和 SQLite 状态管理器 |
| [工具](utilities.md) | 定义该名称的模块 | HTTP 客户端、速率限制器，包括按主机的限制 |

各部分如何协同工作，请参阅[架构](../guide/architecture.md)。
