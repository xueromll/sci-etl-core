# 安装

需要 Python 3.11 或更高版本。

```bash
pip install "sci-etl-core[async,arxiv,llm,pdf]"   # 快速开始用到的全部依赖
pip install "sci-etl-core[full]"                  # 除本地嵌入外的所有内置组件
```

从克隆的仓库安装：

```bash
pip install -e ".[full]"
```

基础安装只依赖 Pydantic。它包括两种流水线、优雅关闭、进度事件和运行指标、组件契约、
配置模型、状态后端、LLM 响应缓存、CSV 和 JSON Lines 导出器、论断与溯源、记录校验器、
LaTeX 解析、文本分块、布尔文本检索、排名融合以及发现图。需要其他包的组件会在你导入该组件
时导入那个包，因此请为你使用的组件添加相应的 extra：

| Extra | 添加的包 | 用于 |
|-------|----------|------|
| `config` | `pyyaml`、`python-dotenv` | `load_config`、`load_config_async`、`load_yaml` |
| `async` | `httpx`、`aiolimiter` | `AsyncArxivExtractor`、`AsyncPubMedExtractor`、`AsyncSemanticScholarExtractor`、`AsyncOpenAlexExtractor`、`build_async_client`、`AioLimiterRateLimiter` |
| `arxiv` | `beautifulsoup4`、`lxml` | `AsyncArxivExtractor`，它还需要 `async` |
| `xml` | `lxml` | `JatsXmlParser`、`DocxParser` 和 `AsyncPubMedExtractor`，后者还需要 `async` |
| `html` | `beautifulsoup4` | `HtmlTextParser`，`AsyncLLMEntityExtractor` 默认用它处理以标记开头的全文 |
| `processors` | `pandas`、`numpy` | `sci_etl_core.processors` 中除校验器外的所有步骤，以及表格输出端 |
| `llm` | `openai`、`tiktoken` | `AsyncOpenAICompatibleClient`、基于 token 的截断 |
| `pdf` | `pdfplumber` | `PdfPlumberParser` |
| `sql` | `sqlalchemy` | `SqlTableSink`，它还需要 `processors` |
| `viz` | `plotly` | `Plotly3DSink`，它还需要 `processors` |
| `cluster` | `scikit-learn`、`numpy` | `ClusteringStep`，它还需要 `processors` |
| `embeddings` | `numpy`、`openai` | `AsyncOpenAIEmbedder`、向量存储、`AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `numpy`、`sentence-transformers` | `AsyncSentenceTransformerEmbedder` |
| `search` | 无 | 无额外功能：`sci_etl_core.search` 只需要标准库，这个 extra 只是记录安装该包的原因 |
| `full` | 上述除 `sentence-transformers` 之外的所有包 | 除本地嵌入外的所有内置组件 |
| `dev` | pytest 及其插件、`hypothesis` | 运行测试套件 |
| `lint` | `ruff`、`mypy`、类型存根 | 对源代码做静态检查和类型检查 |
| `docs` | MkDocs、Material for MkDocs、mkdocstrings、mkdocs-click、mike、mkdocs-static-i18n、`ruff` | 构建本文档站点 |

导入缺少对应 extra 的组件会抛出 `ModuleNotFoundError`，并指明需要安装的包。

!!! tip "只想运行一条流水线？"
    `pip install sci-etl-cli` 会安装 [`sci-etl` 命令](../cli/index.md)，它可以根据一个
    YAML 文件运行 arXiv 提取项目，无需编写组装代码。
