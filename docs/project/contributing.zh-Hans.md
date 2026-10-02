# 为 sci-etl-core 做贡献

感谢你有兴趣改进 `sci-etl-core`！我们真诚欢迎新的提取器、解析器、导出器、嵌入后端以及
文档修正，也欢迎首次贡献者。本指南能帮助你快速上手。

参与即表示你同意遵守我们的[行为准则](code-of-conduct.md)。

## 开发环境设置 {#development-setup}

```bash
git clone https://github.com/xueromll/sci-etl-core.git
cd sci-etl-core

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[full,dev]"
```

- **需要 Python 3.11+**；代码库使用了 `X | Y` 联合类型，以及带 `slots=True`、
  `kw_only=True` 的 dataclass。
- **为什么要 `[full]`：** 测试套件会用到每个内置组件。
- **测试不需要：** `sentence-transformers` 和真实的 SQL 驱动，它们都会被模拟或替换为桩。

## 代码库如何运作：请先阅读 {#how-the-codebase-works-read-this-first}

- **异步是唯一的实现。** 每个组件都是 `async` 的。不要为组件添加同步的孪生版本；这里没有
  代码生成器。阻塞式实现通过 `_adapters.py` 中的适配器接入流水线。
- **只有一个阻塞式入口。** `ETLPipeline`（`pipeline.py`）通过 `_sync_bridge.run_sync` 运行
  `AsyncETLPipeline`。新的阻塞式 API 请先在议题中讨论。
- **保持事件循环空闲。** 用 `asyncio.to_thread` 运行 CPU 密集型或阻塞式工作。解析器、
  pandas、`sqlite3` 和文件 IO 都遵循这一模式。
- **注入协作组件。** 客户端、解析器、`sleep` 和 `logger` 都是构造函数参数，以便测试替换。
  凡是涉及计时或重试的地方，都要接受 `logger: Callable[[str], None] | None` 和可注入的
  `sleep`。
- **永远不要吞掉取消。** 在捕获宽泛的异常之前，先捕获并重新抛出 `asyncio.CancelledError`
  （参见 `llm/relevance_async.py`）。
- **用异常表示失败。** 使用 `exceptions.py` 中的异常层级。遇到传输故障时不要返回 `None` 或
  空结果：流水线依靠 `UpstreamError` 和 `MalformedResponseError` 区分故障与数据结尾。
- **保证并发安全。** 流水线会并发调用相关性过滤器、实体提取器、导出器的 `write` 和
  `mark_processed`。请用 `asyncio.Lock` 串行化共享写入，并用
  `_atomic_io.atomic_write_text` 写文件。`AsyncCsvExporter` 和 `AsyncFileStateManager` 是
  很好的范例。
- **通过模块记录器输出日志。** 每个模块都用 `_logger = logging.getLogger(__name__)` 记录
  日志：会改变运行产出或成本的情况用 `WARNING`，运行所报告的输出端或存储故障用 `ERROR`，
  例行说明用 `INFO`。永远不要配置处理器或级别，那是应用程序的事。
- **让可选导入保持惰性。** 每个包的 `__init__.py` 都在 `_EXPORTS` 中把公开名称映射到其模块，
  并在首次访问时加载，因此导入一个组件永远不需要另一个组件的可选依赖。请在那里以及对应的
  `TYPE_CHECKING` 导入中注册新的公开名称（有测试会检查两者是否一致），并把任何新的第三方
  依赖加入 `pyproject.toml` 中的某个 extra。
- **核心库中不放特定领域的常量**；保持其与领域无关。

## 运行测试 {#running-tests}

测试套件离线运行，不需要网络、真实的 LLM 或嵌入服务。

```bash
pytest                                                # 全部离线测试
pytest tests/async                                    # 异步组件
pytest tests/contract                                 # ABC 一致性
pytest --cov=sci_etl_core --cov-report=term-missing   # 覆盖率报告
```

- **覆盖率保持在 100%。** 覆盖率低于 100% 时，`pytest --cov=sci_etl_core` 会失败（在
  `pyproject.toml` 中配置），因此新增和修改的代码都需要有覆盖它的测试。只有在测试平台上无法
  运行的行（例如特定于操作系统的导入）才使用 `# pragma: no cover`。CI 还会测量分支覆盖率并
  在作业摘要中报告；目前它还不是强制门槛。
- **异步测试**使用显式的 `@pytest.mark.asyncio` 标记（未配置自动模式），并配合
  `AsyncMock` 或 `mocker` fixture。
- **不访问真实网络，也不进行退避等待。** 模拟 HTTP、LLM 和嵌入客户端，并注入
  `sleep=AsyncMock()` 来跳过退避延迟。
- **契约测试。** 每个公开 ABC 的实现在 `tests/contract/test_abc_conformance.py` 中都有一个
  测试用例；每新增一个实现都要添加一个。
- **属性测试。** 把不变式（尤其是两个后端必须共享的不变式，例如内存和 SQLite 嵌入存储）放进
  `tests/test_properties.py` 中的 Hypothesis 测试。
- **公开接口快照。** `tests/api/public_surface.txt` 记录了每个稳定的类、字段、方法和函数
  签名，当代码与之不再一致时，`tests/api/test_public_surface.py` 会失败。当你有意修改公开
  API 时，请重新生成快照，提交差异，并为其添加一条 CHANGELOG.md 记录：

  ```bash
  python tests/api/update_surface.py
  ```

  `tests/api/surface.py` 列出了稳定名称。[sci-etl-cli](https://github.com/xueromll/sci-etl-cli)
  或 [udg-catalogue](https://github.com/xueromll/udg-catalogue) 导入或继承的每个名称都必须在
  其中。`tests/api/consumer_surface.txt` 列出了这些名称。当使用方锁定的版本发生变化时，请
  重新生成它，并从已获取的远程分支读取星表项目，而不是从可能落后的本地克隆读取：

  ```bash
  git -C ../udg-catalogue fetch origin
  python tests/api/scan_consumers.py sci-etl-cli=../sci-etl-cli udg-catalogue=../udg-catalogue@origin/main
  ```
- **在线测试。** `tests/live` 对每个内置来源运行一次小型查询，并检查返回的记录、元数据和
  全文。这些测试默认不被选中。Live 工作流每晚运行它们，而且从不作为必需的检查。可以在本地用
  `pytest -m live tests/live` 运行。用于获得更高速率上限的密钥是可选的，从 `NCBI_API_KEY`、
  `SEMANTIC_SCHOLAR_API_KEY` 和 `OPENALEX_MAILTO` 读取。没有相应密钥时，持续返回 `429` 的
  来源会被跳过，而不是判为失败。
- **吞吐量基准测试。** `python benchmarks/run_throughput.py` 让每个内置的流水线导出器在
  1,000、10,000 和 50,000 条记录下通过 `AsyncETLPipeline` 运行，并把耗时写入
  `benchmarks/results/<version>.json`。如果某个导出器在最大规模下每条记录的耗时不超过最小
  规模下的 1.5 倍，就认为它是线性的。`--sizes`、`--repeats` 和 `--exporters` 可以缩小运行
  范围。
- **下游测试。** Downstream 工作流会在每次 push 和 pull request 时运行
  [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) 和
  [udg-catalogue](https://github.com/xueromll/udg-catalogue) 的测试套件，用当前检出的代码
  替换各项目锁定的版本，并在出现任何 `DeprecationWarning` 时失败。每个作业都会安装项目自身
  依赖声明中指定的 extra。在本地运行 CLI 测试套件：

  ```bash
  git clone https://github.com/xueromll/sci-etl-cli.git ../sci-etl-cli
  pip install -e ".[config,async,arxiv,html,llm,pdf]"
  pip install --no-deps -e ../sci-etl-cli
  pip install click rich pytest pytest-asyncio pytest-mock pytest-cov
  cd ../sci-etl-cli && python -m pytest -W error::DeprecationWarning
  ```

  以及 udg-catalogue 测试套件，它还会安装 CPU 版本的 PyTorch：

  ```bash
  git clone https://github.com/xueromll/udg-catalogue.git ../udg-catalogue
  export PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
  pip install -e ".[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]" \
      -r ../udg-catalogue/requirements/app.txt -r ../udg-catalogue/requirements/dev.txt
  cd ../udg-catalogue && python -m pytest -W error::DeprecationWarning
  ```

## 代码风格 {#code-style}

- 遵循 **PEP 8** 命名：函数和变量用 `snake_case`，类用 `CapWords`，常量用 `UPPER_CASE`。
- **每个公开签名都要有类型注解。** 本包附带 `py.typed`；请保持注解准确。
- **短小、职责单一的函数。** 优先使用组合和依赖注入，而不是基于硬编码逻辑进行分支。
- **用文档字符串说明契约和意图。** 记录 `Raises:` 以及不明显的决定；不要写复述代码的注释。
- 标识符和文档字符串使用**美式英语**。

ruff 和 mypy 会在每次 push 和 pull request 时在 CI 中运行，配置位于 `pyproject.toml`。除了
pycodestyle、Pyflakes、isort 和 bugbear 规则之外，ruff 还会检查 `ASYNC`、`UP`、`RUF` 和
`PT` 规则集。mypy 以更严格的选项检查核心契约（`models`、`exceptions`、`observability`、
`pipeline_async` 以及每个 `async_base` 模块）：不允许无类型定义、不允许裸泛型、不允许返回
`Any`、不允许隐式再导出。在提交 PR 之前请运行这两者：

```bash
pip install -e ".[full,dev,lint]"
ruff check .
mypy
```

`ruff check --fix .` 会对导入排序并应用其他安全的修复。代码格式不做强制要求，因此请不要在
PR 中夹带无关的格式调整。请把面向用户的变更记录在 [CHANGELOG.md](changelog.md) 的未发布
版本下。

## 文档 {#documentation}

文档站点使用 [MkDocs](https://www.mkdocs.org/) 和
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)，根据 `mkdocs.yml` 和
`docs/` 文件夹构建，并发布到 GitHub Pages。

```bash
pip install -e ".[docs]"
git clone https://github.com/xueromll/sci-etl-cli.git ../sci-etl-cli
pip install --no-deps -e ../sci-etl-cli
mkdocs serve                                          # 在 http://127.0.0.1:8000 预览
mkdocs build --strict                                 # CI 运行的检查
```

- **页面所在位置。** 指南是 `docs/` 下的 Markdown 文件，列在 `mkdocs.yml` 的 `nav` 中。
  `CHANGELOG.md`、`MIGRATION.md`、`ROADMAP.md`、本指南、`SECURITY.md` 和
  `CODE_OF_CONDUCT.md` 都保留在仓库根目录；`docs/project/` 下的页面负责渲染它们，并为站点
  改写它们之间的链接。
- **翻译。** 页面的俄语、西班牙语、简体中文和阿拉伯语版本以 `page.ru.md`、`page.es.md`、
  `page.zh-Hans.md` 和 `page.ar.md` 的形式放在原页面旁边，由 mkdocs-static-i18n 插件把每种语言
  构建到各自的路径下，例如 `/ru/`。修改英文页面的 pull request 也要同时更新它的四个译本。
  这四种译本目前都是机器翻译，尚待母语者审校，因此英文是权威文本。
  [TRANSLATING.md](translating.md) 列出了每种语言的协调人，并包含术语表以及译文页面需要
  遵循的规则。
- **CLI 部分**来自 sci-etl-cli 仓库的 `docs/` 文件夹和 `nav`。构建时会在本仓库旁边或
  `SCI_ETL_CLI_DIR` 指定的路径查找检出副本；找不到时会省略该部分，而 `--strict` 会把这报告
  为失败。请在那个仓库中修改 CLI 页面。
- **API 参考。** `docs/reference/` 下的页面根据文档字符串生成。新的公开模块需要在其中某个
  页面上添加一条 `::: module.path` 条目；在添加之前，`tests/test_docs.py` 会一直失败。
- **代码示例。** `tests/test_docs.py` 还会检查 `docs/` 下的每个 Python 示例都能编译，并且
  它从 `sci_etl_core` 导入的每个名称都存在，因此重命名公开名称时也要更新示例。
- **发布。** 文档工作流把 `master` 部署为 `dev` 版本，把每个 `v*` 标签部署为其次版本（例如
  `0.3`），并带有 `latest` 别名。基于标签的构建使用 sci-etl-cli 最新版本中的 CLI 页面；如果
  该版本没有 `mkdocs.yml`，则使用其默认分支。无需手动发布任何内容。

## 发布版本 {#releasing}

- **开发版本。** 发布之后，`master` 会立即切换到下一个开发版本（例如 `0.6.0` 之后的
  `0.7.0.dev0`），这样从 `master` 构建的产物永远不会自称是正式版本。
- **发布门槛。** 推送 `v*` 标签会在被标记的提交上运行 CI 测试套件和 Downstream 工作流。只有
  两者都通过时才会构建并发布发行包，因此会破坏 sci-etl-cli 或 udg-catalogue 的版本永远不会
  被发布。标签必须与 `pyproject.toml` 中的版本一致。
- **弃用。** 自 0.6.0 起，已弃用的名称在被移除之前至少还能在两个次版本中使用。
- **打标签之前。** 为 `CHANGELOG.md` 的未发布部分填上日期，更新 `SECURITY.md` 中受支持的
  版本，并重新运行 `python benchmarks/run_throughput.py`，让 `benchmarks/results/` 包含新
  版本的结果。
- **锁定的 action。** 工作流把每个 action 锁定到某个提交 SHA，并在行尾注释中写明标签，例如
  `# v5`。要升级到更新的版本，请用
  `git ls-remote https://github.com/actions/checkout refs/tags/v5` 查出其 SHA，并同时更新
  锁定值和注释。

## 提交格式 {#commit-format}

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <short summary>
```

常用类型：`feat`、`fix`、`docs`、`test`、`refactor`、`perf`、`chore`。用 `!` 标记破坏性
变更（例如 `refactor(core)!: ...`）。

示例：

```
feat(extractors): add PubMed async extractor
fix(exporters): serialize concurrent CSV upserts
docs(readme): document ETLPipeline event-loop behavior
```

摘要请使用祈使语气，并控制在约 72 个字符以内。在正文中引用议题（`Closes #123`）。

## Pull request 流程 {#pull-request-process}

1. **先创建议题**：任何不简单的改动都请先开议题，以便我们就方案达成一致。
2. **从 `master` 创建分支**，例如 `feat/pubmed-extractor`。
3. **随改动一起编写测试**；保持覆盖率为 100%。
4. 在本地**运行**测试套件（如果你使用静态检查和类型检查，也一并运行）。
5. 为面向用户的变更**更新文档**：
   - 用法写在 `docs/` 下的页面中；`README.md` 只保留简短概述
   - 你修改的每个英文页面的俄语、西班牙语、中文和阿拉伯语译本，按照
     [TRANSLATING.md](translating.md) 的规定更新；如果你无法写其中某种语言，请说明，由该语言的
     协调人在合并之前补上
   - 破坏性变更写进 `MIGRATION.md`，放在包含该变更的版本之下
   - 当变更影响把现有流水线迁移到本库时，更新 `docs/guide/migrating-a-pipeline.md`
   - 当你完成了列出的事项时，更新 `ROADMAP.md`
   - 任何破坏性变更都要写进 pull request 描述，并说明用户需要更新什么
6. **填写** [pull request 模板](https://github.com/xueromll/sci-etl-core/blob/master/.github/PULL_REQUEST_TEMPLATE.md)。
7. **让 PR 保持专注**：每个 PR 只包含一个逻辑变更，最便于审查。

维护者会及时审查。你可以期待友好、建设性的交流；提出的修改意见针对的是代码，绝不是针对你。

## 添加新组件 {#adding-a-new-component}

大多数贡献都是接入某个现有的抽象基类：

| 组件 | 继承 | 实现 | 契约 |
|------|------|------|------|
| 提取器 | `AsyncExtractor` | `async fetch_page(query, cursor, page_size) -> ListingPage`、`async fetch_full_text`；当游标是十进制偏移量时实现 `cursor_for_offset` | 返回它能读取的每个条目：流水线会跳过已处理的 id。把没有 id 的条目计入 `entries`，在最后一页返回 `next_cursor=None`，在达到来源自身结果上限的那一页返回 `truncated=True`。重试后仍无法连接来源时抛出 `UpstreamError`，来源直接拒绝请求时抛出 `ExtractionError`，列表无法读取时抛出 `MalformedResponseError`，来源不再接受游标时抛出 `StaleCursorError`。 |
| 解析器 | `Parser`（可选 `TableParser`） | `extract_text(content: bytes) -> str` | 同步执行；调用方在工作线程中运行它。遇到无法读取的字节时抛出 `ParsingError`。 |
| LLM 客户端 | `AsyncLLMClient` | `async complete_json(system_prompt, user_content, timeout)`；可选 `complete_structured(..., schema, timeout)` 和 `invalidate(..., schema=None)` | 返回解析后的 JSON 对象；失败或响应体不是 JSON 对象时抛出 `LLMError`。当服务商支持 JSON Schema 输出时重写 `complete_structured`；默认实现调用 `complete_json`。 |
| LLM 响应缓存 | `AsyncLLMResponseCache` | `async get(key)`、`async set(key, response)`、`async clear()` | 键不存在时 `get` 返回 `None`。返回副本，以免调用方修改响应时改动缓存。存储故障时抛出 `LLMCacheError`；`CachingLLMClient` 会记录它并改为调用 LLM。如果持有连接，请添加 `aclose()`。 |
| 相关性过滤器 | `AsyncRelevanceFilter` | `async is_relevant(record)` | 重新抛出 `CancelledError`。 |
| 实体提取器 | `AsyncEntityExtractor[E]` | `async extract(text) -> Sequence[E]`；需要记录时实现 `extract_record(record, text)` | 流水线调用 `extract_record`，其默认实现调用 `extract`。失败时抛出异常，而不是返回 `[]`，以便重试该记录。需要记录的提取器设置 `requires_record = True`；包装层委托给内层的 `extract_record`。 |
| 导出器 | `AsyncExporter[E]` | `async write(record, entities)`；可选 `open`、`flush`、`aclose` 和 `durable_writes` | 在构造函数中接收目标位置。`write` 会对每条已处理的记录运行（包括没有实体的记录），可能是并发的，并且必须是幂等的。当 `durable_writes = False` 时，`flush` 必须让之前的每次写入都持久化。 |
| 状态管理器 | `AsyncStateManager` | `load_processed_ids`、`mark_processed`、`load_metadata`、`save_metadata` | 必须并发安全。重写 `record_failure` 和 `failure_counts` 以支持隔离；默认实现不做任何跟踪。记录模式版本，并拒绝来自更新版本的文件。如果使用缓冲，请重写 `flush()`；如果持有连接，请添加 `aclose()`。 |
| 嵌入器 | `AsyncEmbedder` | `async embed(texts) -> list[list[float]]` | 每个输入对应一个向量，顺序相同；失败时抛出 `EmbeddingError`。 |
| 向量存储 | `AsyncEmbeddingStore` | `add`、`delete_record`、`query`、`count` | 替换具有相同 `(record_id, chunk_index)` 的文本块；`delete_record` 删除某条记录的所有文本块。如果你的后端能原子地完成删除和添加，请重写 `replace_record`（默认先删除再添加）。永远不要返回分数非有限的结果。在 `top_k`、`min_score` 和 `exclude_record_id` 上与 `InMemoryEmbeddingStore` 的行为一致。串行化对共享连接的使用，并抛出 `EmbeddingStoreError`。如果希望文本索引能从你的存储回填，请实现 `iter_records`（段落按 `chunk_index` 排序，记录按 `record_id` 排序，不含向量）。 |
| 分块器 | `TextChunker` | `chunk(text) -> list[str]` | 覆盖整段文本的有序段落。 |
| 文本检索存储 | `AsyncTextSearchStore` | `facet_keys` 属性、`index`、`delete_record`、`search`、`filter_ids`、`get_documents`、`facet_counts`、`count` | 接收已解析的查询，绝不接收文本。用 `require_rankable` 拒绝 `search` 无法排序的查询。分数相同时按 `record_id` 排序，并在 `limit` 之前应用过滤器。对于不在 `facet_keys` 中的过滤器键或分面键，或对同一个键使用两个过滤器的情况，在任何 I/O 之前抛出 `ValueError`（`validate_filters`、`validate_facet_keys`）。接受 `MetadataFilter` 和 `RangeFilter`，用 `tag_in_range` 比较范围，并为每个有高亮匹配的字段填写 `TextHit.snippets`。如果能在一次读取中完成计数，请重写 `range_counts`（默认每个范围调用一次 `filter_ids`）。结果与 `InMemoryTextSearchStore` 一致，并抛出 `SearchStoreError`。 |
| 边来源 | `AsyncEdgeSource` | `kind` 属性、`async neighbours(record_ids, limit)` | 把每个请求的 id（即使没有邻居）映射到最多 `limit` 个 `(record_id, weight)` 对，最好的排在前面，权重越高表示越相关。永远不要关闭传给你的存储。 |
| 处理器 | `Processor` | `process(frame) -> DataFrame` | 不要修改输入的 DataFrame。 |
| 校验器 | `RecordValidator` | `is_valid(record) -> bool`；可选 `validate(record) -> ValidationResult` | 作用于单个实体字典。重写 `validate` 以指明每次拒绝的字段和规则；它拒绝的内容必须与 `is_valid` 完全相同。 |

在新类所在子包的 `_EXPORTS` 映射和 `TYPE_CHECKING` 导入中注册它。新模块还需要在
`docs/reference/` 下它所属的页面上添加条目。如果它是主要的面向用户的类，请以同样的方式把它
加入 `sci_etl_core/__init__.py`。在 `tests/contract/test_abc_conformance.py` 中为它添加一个
测试用例。

祝你编码愉快，感谢你的贡献！
