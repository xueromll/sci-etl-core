# 何时不应使用

`sci-etl-core` 只做一件事：输入科学论文，输出结构化、可检索的数据。本页列出它不适用的
情况，以及你需要自行构建的部分比预期更多的情况，便于你在安装之前做出判断。

## 只需从少量论文中取几个值 {#you-need-a-few-values-from-a-handful-of-papers}

状态文件、列表游标、可续跑的运行和缓存，只有在语料库大到读不完、需要随着新论文出现反复
提取，或需要把每个值追溯到其来源时才划算。如果只是手头的几篇论文，直接阅读，或者粘贴到
聊天助手里，比编写提示词、实体模型和流水线更快。

## 你的论文不在内置来源中 {#your-papers-arent-on-a-bundled-source}

内置提取器覆盖 arXiv、PubMed、Semantic Scholar 和 OpenAlex。bioRxiv、ChemRxiv、
Crossref、出版商网站以及你磁盘上的 PDF 文件夹，都需要你自己编写 `AsyncExtractor`。如
[编写提取器](../guide/sources.md#writing-an-extractor)所示，契约只有三个方法；但如果你
不想编写，流水线就没有可运行的数据源。解析器、检索和 LLM 组件仍可单独使用。

## 所需的值在付费墙之后 {#the-values-you-need-are-behind-a-paywall}

全文只来自开放来源：arXiv 的 LaTeX 和 PDF、PubMed Central 的 JATS XML，以及 Semantic
Scholar 和 OpenAlex 链接的开放获取 PDF。本库从不登录出版商网站，也不使用机构访问权限。
论文没有开放全文时，其记录会退回到摘要；因此在大多数论文需要付费的领域，大多数记录只能让
LLM 读到摘要。

## 值只存在于图表或扫描页中 {#the-values-live-in-figures-or-scanned-pages}

`PdfPlumberParser` 读取 PDF 的文本层，包括其中的表格。它不做 OCR，也不读取图像，因此只
出现在曲线图、插图或扫描页中的值，对提取来说是不可见的。当 PDF 完全提取不出文本时，记录会
退回到摘要。

## 每个值都必须无需复核即正确 {#every-value-must-be-correct-without-review}

每篇论文都由 LLM 阅读，因此某个值可能是错误的、张冠李戴的或被遗漏的。类型化实体、记录
校验器，以及保留每个值出处句子的[论断](../guide/claims.md)，可以帮助你发现并核查错误，
但不能消除错误。同一条提示词换一个模型或模型版本也可能给出不同的回答，而
[响应缓存](../guide/llm-caching.md)只是重复先前的回答，并不能让模型变得确定。如果每个值都
必须正确（例如用于监管申报或临床决策），请为逐一人工核查每个值预留时间，或者不用 LLM
进行提取。

## 需要系统综述级别的完整性 {#you-need-systematic-review-completeness}

一次运行可能通过三种方式漏掉相关论文：

- **来源上限。** PubMed 只提供查询的前 9,999 条结果，Semantic Scholar 只提供前 1,000 条。
  如[运行语义](../guide/run-semantics.md#capped-listings)所述，更窄的查询（例如按日期范围）
  可以覆盖其余结果。
- **自动筛选。** 相关性过滤器根据标题和摘要，借助 LLM 或嵌入相似度做出判断，因此相关论文
  可能被标记为不相关，从而永远不会被获取。
- **缺少全文。** 只通过摘要读取的论文，即使正文中有相关的值，也可能提取不出任何值。

对于必须说明每篇纳入和排除论文的综述，请使用配有人工审阅者的专用筛选软件；如果要用本库，
也只用于筛选后纳入的论文。

## 不能把论文文本发送给 LLM {#you-cant-send-paper-text-to-an-llm}

每条相关记录至少需要对其全文调用一次 LLM，因此成本随语料库增长。任何支持 OpenAI 聊天 API
的端点都可以使用，包括 vLLM、llama.cpp 和 Ollama 等本地服务器，因此文本可以留在你自己的
机器上。没有此类端点的服务商需要你自己实现 `AsyncLLMClient`。完全不用 LLM 时，实体提取
无法运行，但检索和语义记忆组件仍然可用：SQLite 文本索引只需要标准库，
`AsyncSentenceTransformerEmbedder` 可以在本地生成嵌入。

## 需要检索服务或大型向量数据库 {#you-need-a-search-service-or-a-large-vector-database}

检索在你的机器上基于 SQLite 文件运行：

- `AsyncSqliteEmbeddingStore` 每次查询都会为所有已存储的向量打分，并把向量保存在内存中，
  因此查询时间和内存占用都随语料库增长。目前还没有近似最近邻索引；
  [路线图](../project/roadmap.md#later)把它列为等待有实际需求的语料库再启动的事项。
- 状态管理器依赖本地文件锁和单一的 SQLite 写入者，并且不计划支持分布式执行。大型语料库可以
  拆分到多次相互独立、各自拥有状态的运行中处理。
- 没有服务器、认证或多用户访问功能。

如果需要托管的多用户服务，或在超大语料库上进行交互式语义检索，请把数据放入专用的搜索引擎
或向量数据库中，可以通过导出，也可以通过你自己实现的 `AsyncEmbeddingStore`。

## 需要检索中文、日文或韩文文本，或需要子串匹配 {#you-search-chinese-japanese-or-korean-text-or-need-substring-matches}

文本索引按空格和标点切分词语，与 SQLite 的 `unicode61` 分词器相同。一串不含空格的中文、
日文或韩文字符会被索引为一个 token，因此检索其中的某个词什么也找不到，前缀查询也只能从这串
字符的开头匹配。词内匹配（例如在 `protogalaxy` 中找到 `galaxy`）同样不受支持。基于嵌入的
语义检索不依赖分词器。

## 想用阻塞式代码编写组件 {#you-want-to-write-components-as-blocking-code}

如[阻塞式用法](blocking-usage.md)所示，`ETLPipeline` 可以从阻塞式代码运行流水线，但
提取器、相关性过滤器、实体提取器、LLM 客户端、导出器和状态管理器的契约都是异步的。你自己
编写的组件必须是 `async` 实现；不计划提供这些契约的阻塞版本。解析器和 pandas 处理器仍然是
阻塞式的。

## 需要 1.0 的稳定性保证 {#you-need-a-10-stability-guarantee}

本库目前是 0.6 版。1.0 之前计划的所有破坏性变更都已发布，已弃用的名称至少在两个次版本内
仍可使用，但临时性名称（例如 `sci_etl_core.claims` 中的名称）仍可能在次版本中变化。请锁定
一个次版本范围，例如 `>=0.6,<0.7`，并在升级前阅读[迁移指南](../project/migration.md)。

## 想要图形界面工具 {#you-want-a-graphical-tool}

本库是一个 Python API。[sci-etl-cli](../cli/index.md) 可以根据 YAML 文件运行流水线而无需
编写组装代码，但它仍是命令行工具。两者都不附带图形界面；你需要自己构建，就像 udg-catalogue
为其仪表盘所做的那样，[构建用户界面](../guide/search/user-interfaces.md)介绍了检索组件为
界面提供了哪些可渲染的内容。

## 你的文档不是科学论文 {#your-documents-arent-scientific-papers}

解析器可以读取任何来源的 PDF、HTML、DOCX、LaTeX 和 JATS XML，但提取器、记录元数据和
检索字段（标题、摘要和正文）都是为论文设计的。专利、法律文书、新闻和网页并不适合，针对它们
的功能也超出了本库的范围。通用的文档处理框架更适合它们。

## 如果以上都不适用 {#if-none-of-these-apply}

请从[安装](installation.md)和[快速开始](quick-start.md)开始。
