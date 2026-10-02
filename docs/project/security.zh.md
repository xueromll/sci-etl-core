# 安全策略

我们非常重视 `sci-etl-core` 及其用户的安全。感谢你帮助保障本项目及其社区的安全。

## 受支持的版本 {#supported-versions}

| 版本 | 是否支持 |
|------|----------|
| 0.6.x | ✅ |
| < 0.6 | ❌ |

安全修复会发布在最新的次版本中。在报告旧版本中的问题之前，请先升级。

## 报告漏洞 {#reporting-a-vulnerability}

**请不要为安全漏洞创建公开的议题。**

请通过电子邮件私下报告至 **lanhua1122333@gmail.com**，并提供：

- 漏洞的描述及其潜在影响。
- 复现步骤（如有可能，请提供概念验证）。
- 受影响的版本和环境详情。
- 你建议的修复方案（如果有的话）。

### 你可以期待什么 {#what-to-expect}

- 在 48 小时内**确认收到**。
- 在 5 个工作日内给出初步**评估**。
- 协调披露：我们会与你商定时间表，发布修复，并在发布说明中致谢，除非你希望保持匿名。

请在任何公开披露之前，给我们合理的修复时间。

## 密钥管理 {#secret-management}

`sci-etl-core` 的设计目标是让凭据远离代码、日志和版本控制：

- **API 密钥使用 `SecretStr`。**
  - `LLMConfig.api_key` 是 Pydantic `SecretStr`，因此密钥不会出现在 repr、日志行或回溯信息
    中。
  - `AsyncOpenAICompatibleClient` 和 `AsyncOpenAIEmbedder` 直接接受 `SecretStr`，只在创建
    底层客户端时才将其解包。
- **来自环境的密钥。**
  - `load_config` 从环境变量读取密钥（默认是 `LLM_API_KEY`；可通过 `api_key_env_var`
    配置）。
  - 只有在你传入 `env_path` 或 `load_env=True` 时才会读取 `.env` 文件，并且环境中已设置的
    变量优先于它。
- **不要把密钥写进 YAML。** 已设置的环境变量总是会覆盖 YAML 文件中的 `llm.api_key`，后者只
  作为后备。提交到配置文件中的密钥仍然是泄露。
- **配置错误不会回显值。** `load_config`、`load_config_async` 和 `validate_config` 会指明
  每个出错的键及原因，但从不显示其值，也不会链接 pydantic 的错误，因为后者可能包含原始设置。
  YAML 使用 `yaml.safe_load` 解析。
- **永远不要提交 `.env`。** 把 `.env` 加入 `.gitignore`，并像本仓库一样分发一个带占位值的
  `.env.example`。
- **数据库 URL 同样是机密。** `SqlTableSink` 以普通字符串 `url` 的形式接收其 SQLAlchemy URL。
  请在运行时根据环境构建它，并且不要把它写入日志。

## 数据处理 {#data-handling}

- **存储的文本未加密。**
  - `AsyncSqliteEmbeddingStore` 和 `AsyncSqliteFts5Store` 会持久化全文段落及其标题和来源
    URL。
  - `AsyncSqliteLLMResponseCache` 以 JSON 形式持久化模型响应。
  - `AsyncSqliteClaimStore` 和 `AsyncSqliteRejectionStore` 会持久化提取出的值，以及从每篇
    论文中引用的证据句。
  - 状态文件和状态数据库（其中记录了每条失败记录的最后一次错误），以及 CSV 和 JSON Lines
    输出，都是普通文件。
  - 如果你的语料库受许可限制或较为敏感，请使用文件系统权限和静态加密。
- **CSV 公式注入。** 每个单元格都直接来自 LLM 的输出。默认情况下，`AsyncCsvExporter` 会在
  任何以 `=`、`+`、`-`、`@`、制表符或回车开头的单元格前加一个撇号，以免电子表格对其求值。
  `-5.361` 这样的普通数字保持不变。对于人们会用电子表格软件打开的文件，请保持
  `escape_formulas` 开启。其他输出（`AsyncJsonlExporter` 生成的 JSON Lines、`SqlTableSink`
  写入的 SQL 表、`Plotly3DSink` 生成的 Plotly 悬停文本，以及你自己的导出器和输出端）都不会
  转义。
- **输出中不含机密。** 导出器只写入传给它们的数据；请在导出之前清除包含凭据的字段。

## 不可信输入 {#untrusted-input}

- **来自第三方的文档。**
  - PDF 和 LaTeX 解析针对的是下载的内容。
  - LaTeX 压缩包在内存中读取（其中的成员永远不会被解压到磁盘）。下载大小和解压后的大小默认
    不受限制，因此恶意文件可能耗尽内存。
  - 请对其加以限制：向提取器传入 `max_download_bytes`，它会在解码后限制每个响应体的大小；
    向 `LatexTarballParser` 传入 `max_tex_bytes`，它会限制从一个 e-print 中解压出的 TeX。
    过大的全文下载或 e-print 会被记录并跳过。
  - 除了下载大小之外，PDF 解析不受限制。请在沙盒化、资源受限的环境中处理大型或不可信的
    语料库。
- **提示词注入。**
  - 论文文本会被发送给 LLM，其内容可能左右模型的输出。
  - 请把提取出的实体视为不可信：在下游使用之前对其进行校验（例如使用
    `NumericRangeValidator` 和 `KeywordExclusionValidator`）。
- **出错时放行的相关性过滤器。**
  - `AsyncLLMRelevanceFilter` 和 `AsyncEmbeddingRelevanceFilter` 默认
    `default_on_error=True` 且 `default_on_empty_abstract=True`，因此在服务中断期间每条记录
    都会通过。
  - 如果过滤器起到管控作用，请设置 `default_on_error=False`。这时过滤器在出错时会关闭：调用
    失败或结论不明确都会抛出异常，因此该记录既不会被提取，也不会被标记为已处理。流水线会计入
    一次失败的尝试，并在下一次运行时重试该记录。
  - `default_on_empty_abstract=False` 会把每条没有摘要的记录永久标记为已处理且不相关。只有
    当这类记录永远不应被提取时才设置它。
- **模型下载。**
  - `AsyncSentenceTransformerEmbedder(model_name)` 会在首次使用时下载模型权重。
  - 请使用可信且锁定版本的模型，或者注入一个由你审核过的权重构建的预加载 `model=`。

## 加固建议 {#hardening-recommendations}

- 定期轮换 API 密钥，并按最小权限原则限定其范围。
- 锁定依赖版本并关注安全公告，尤其是以下依赖：
  - 每次安装都需要的校验库：`pydantic`
  - 网络和 LLM 客户端：`httpx`、`aiolimiter`、`openai`、`tiktoken`
  - 文档、标记和配置解析：`pdfplumber`、`beautifulsoup4`、`lxml`、`pyyaml`、
    `python-dotenv`
  - 数据与数值计算：`pandas`、`numpy`、`scikit-learn`
  - 存储与绘图：`SQLAlchemy`、`plotly`
  - `sentence-transformers`（如果已安装）
- 在把用户提供的任何查询字符串、文件路径和目标位置传给提取器或导出器之前，先对其进行校验和
  清理。

## 适用范围 {#scope}

本策略涵盖 `sci-etl-core` 代码库。第三方依赖中的漏洞应向其上游报告，不过如果你能提前告知
我们，以便我们在自己这边锁定版本或打补丁，我们会非常感谢。
