# sci-etl-core

`sci-etl-core` 是一个 Python 库，用于把任何科学领域的论文转换为结构化、可检索的数据。
它从 arXiv、PubMed、OpenAlex 和 Semantic Scholar 获取论文，读取全文，用 LLM 提取你需要
的值，并让这些论文在你自己的机器上保持可检索。

udg-catalogue 展示了这样的成果。它在 arXiv 上筛选天体物理学论文，提取超弥散星系的测量值，
发布了一个包含 1,927 个天体的交叉匹配星表，并支持对其背后的论文进行关键词检索和语义检索。
`sci-etl-core` 提供获取、解析、提取、缓存、可续跑的状态和检索，而 udg-catalogue 补充了
天文学部分：提示词、校验规则、天球位置匹配和仪表盘。

本库中没有任何部分绑定于天文学。领域知识存在于你的提示词、校验器和规范化器中，因此同样的
构建模块适用于任何科学领域。

<div class="grid cards" markdown>

- **通过 YAML 运行**

    ---

    无需编写组装代码，即可初始化、校验、检索和运行提取项目。

    [sci-etl-cli](cli/index.md)

- **查看一个完整项目**

    ---

    从一条 arXiv 查询，到一份已发布的星表以及其背后论文的可检索记忆。

    [完整演练](guide/migrating-a-pipeline.md) ·
    [udg-catalogue](https://github.com/xueromll/udg-catalogue)

- **开始使用**

    ---

    安装所需的 extra，在 arXiv 上运行你的第一条流水线，然后把它指向
    [PubMed、Semantic Scholar 或 OpenAlex](guide/sources.md)。

    [安装](getting-started/installation.md) ·
    [快速开始](getting-started/quick-start.md)

- **检索已收集的内容**

    ---

    基于本地 SQLite 索引的布尔检索和混合检索、元数据分面以及相关论文图。

    [本地检索与发现](guide/search/index.md)

- **查找 API**

    ---

    根据源代码生成的所有公开类和函数。

    [API 参考](reference/index.md)

</div>

## 功能 {#features}

- **可插拔的异步接口**覆盖每个阶段：`AsyncExtractor`、`Parser`、`AsyncLLMClient`、
  `AsyncRelevanceFilter`、`AsyncEntityExtractor`、`AsyncExporter`、`AsyncStateManager`，
  以及用于语义记忆的 `AsyncEmbedder`、`TextChunker` 和 `AsyncEmbeddingStore`。可以运行
  整条流水线，也可以只使用需要的部分，例如检索。
- **异步优先的编排**：每个组件都是 `async` 实现。`AsyncETLPipeline` 以有界并发处理记录，
  `ETLPipeline` 则可以从阻塞式代码运行同一条流水线。
- **明确的失败信号**：传输故障或格式错误的列表会以 `PipelineAborted`（携带部分计数）中止
  运行，而不会看起来像数据已经结束。单条失败的记录会被记录到日志并留给下一次运行；如果记录
  持续失败而没有任何记录被处理，运行会停止，而不是白白耗尽列表的其余部分。
- **可续跑、防崩溃的状态**：纯文件或 SQLite 后端记录已处理的 id、列表游标和失败的尝试，
  因此持续失败的记录会被隔离；CSV 和元数据的写入使用原子重命名。按最新优先排序的列表无需
  重新扫描即可获取新论文。
- **优雅关闭**：Ctrl+C 或 SIGTERM 会让正在处理的记录完成，写回状态，并抛出
  `PipelineInterrupted`。
- **礼貌的重试和速率限制**：每个内置提取器以及 OpenAI 兼容的聊天和嵌入客户端都会按照被限流
  响应的 `Retry-After` 头所要求的时长等待（不超过可配置的上限），并接受可以共享、可以按主机
  设置的速率限制器。
- **进度事件、指标和 token 用量**：类型化的逐记录事件、包含计数、耗时和失败情况的运行指标，
  以及每次运行使用的 token。
- **类型化提取和论断**：用 Pydantic 模型描述实体，即可得到经过校验的类型化实体以及每次拒绝
  的原因；也可以提取论断，为每个值保留论文、证据句和所用模型。
- **LLM 响应缓存**：内存或 SQLite 缓存可以在不再次调用 API 的情况下回答重复的提示词。
- **语义记忆（可选）**：把全文分块并嵌入到内存或 SQLite 向量存储中，检索相似文章，或者用
  嵌入相似度代替 LLM 调用来判断相关性。
- **本地检索与发现**：基于只需标准库的 SQLite FTS5 文本索引的布尔查询、融合 BM25 与嵌入
  相似度的混合检索、元数据分面以及相关论文图。
- **处处依赖注入**：HTTP 客户端、解析器、模型、提示词、模式和输出路径都是构造函数参数。
- **内置具体实现**：arXiv、PubMed、Semantic Scholar 和 OpenAlex 提取器；OpenAI 兼容的
  聊天和嵌入客户端；本地 sentence-transformers 嵌入器；PDF / LaTeX / HTML / DOCX /
  JATS XML 解析器；CSV 和 JSON Lines 导出器；SQL 表和 Plotly 3D 图输出端；数据框处理器和
  记录校验器。
- **类型化配置**：来自 YAML 和环境变量，带有 Pydantic 校验，API 密钥使用 `SecretStr`。
- **离线测试套件**：使用模拟对象的 pytest、Hypothesis 属性测试以及 ABC 一致性测试。
- **遵循 PEP 561 的类型信息**（`py.typed`），便于下游代码做类型检查。

## 获取帮助 {#getting-help}

- 问题和缺陷请提交到[问题跟踪器](https://github.com/xueromll/sci-etl-core/issues)。
- 要把现有流水线迁移到本库？请按照[完整示例](guide/migrating-a-pipeline.md)操作。要升级到
  新版本？请参阅[迁移指南](project/migration.md)。
- 欢迎贡献，请参阅[参与贡献](project/contributing.md)。
- 请按照[安全](project/security.md)中的说明私下报告漏洞。
