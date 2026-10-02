# 迁移指南

本指南按从新到旧的顺序，列出升级到 `sci-etl-core` 新版本时现有代码需要做出的改动。
[CHANGELOG.md](changelog.md) 列出了所有变更，包括无需任何操作的新增内容。

请锁定一个次版本范围，例如 `sci-etl-core>=0.6.0,<0.7`，并在测试于下一个次版本上通过之后
再提高上限。从一个次版本升级到更晚的次版本时，请从最旧的开始，依次应用中间每一节的内容。

如果是首次把现有的科研流水线迁移到本库，请按照
[迁移流水线](https://xueromll.github.io/sci-etl-core/latest/guide/migrating-a-pipeline/)中的
完整示例操作。

- [升级到 0.6](#upgrading-to-06)
- [升级到 0.5.1](#upgrading-to-051)
- [升级到 0.5](#upgrading-to-05)
- [升级到 0.4](#upgrading-to-04)
- [升级到 0.3](#upgrading-to-03)

---

## 升级到 0.6 {#upgrading-to-06}

0.6 改变了数据契约：实体提取器返回什么、导出器如何接收实体、本库如何记录日志，以及基础安装
包含什么。这是 1.0 之前最后一个破坏现有契约的版本。请连同你使用的 extra 一起要求新的
次版本：

```text
sci-etl-core[config,async,arxiv,llm,pdf,processors]>=0.6.0,<0.7
```

0.5 写入的状态文件和数据库、LLM 缓存、嵌入存储以及文本索引都能原样打开。已缓存的 LLM 回答
仍然有效：没有模式的请求，其缓存键与 0.5.1 中相同。

### 安装你导入的 extra {#install-the-extras-you-import}

基础安装现在只依赖 Pydantic。PyYAML 和 python-dotenv 移到了 `config` extra，
Beautiful Soup 和 lxml 移到了 `arxiv`、`html` 和 `xml`，pandas 移到了 `processors`。任何
extra 都不再安装 `aiofiles` 和 `aiosqlite`。导入缺少对应 extra 的组件会抛出
`ModuleNotFoundError`，并指明所需的包：

| 你使用的 | 添加的 extra |
|----------|--------------|
| `load_config`、`load_config_async`、`load_yaml` | `config` |
| `AsyncArxivExtractor` | `async`、`arxiv` |
| `AsyncPubMedExtractor` | `async`、`xml` |
| `JatsXmlParser`、`DocxParser` | `xml` |
| `HtmlTextParser`，或用于以标记开头的全文的 `AsyncLLMEntityExtractor` | `html` |
| `sci_etl_core.processors` 中除校验器以外的任何内容 | `processors` |

`full` 仍会安装除本地嵌入之外的所有内置组件。

### 只有在要求时才读取 `.env` 文件 {#env-files-are-read-only-when-asked}

`load_config` 和 `load_config_async` 不再隐式查找 `.env` 文件。请传入该文件，或者要求进行
查找：

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), load_env=True)
config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
```

两者都不使用时，API 密钥必须已经在环境中。

### 导出器接收记录和自己的目标位置 {#exporters-take-the-record-and-their-destination}

`AsyncExporter.export(data, destination)` 被一个生命周期取代。流水线会在第一次列表请求之前
调用 `open()`，对每条已处理的记录（包括没有实体的记录）调用 `write(record, entities)`，在每
一页之后调用 `flush()`，并在运行结束时（无论如何结束）调用 `aclose()`。导出器在构造时接收其
目标位置，因此流水线的 `destination=` 参数已被移除：

```python
from sci_etl_core import AsyncCsvExporter, AsyncETLPipeline

pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager,
)
```

`AsyncCsvUpsertExporter` 已被移除。它的替代者 `AsyncCsvExporter` 不会合并行：它为每个实体
写一行，并带上其来源论文的 `record_id`，把其他键保存在 `extra` 列中，并原样写入值，因此值
永远不会被截断、转换或丢弃，报告同一天体的两篇论文会产生两行。请在后处理中进行合并，在那里
做出明确的选择：

```python
import pandas as pd

from sci_etl_core.processors import DeduplicationStep, DefaultKeyNormalizer, NormalizationStep, ProcessorChain

raw = pd.read_csv("results.csv", dtype={"record_id": str, "name": str})
one_row_per_name = ProcessorChain(
    [NormalizationStep("name", DefaultKeyNormalizer()), DeduplicationStep("_norm_key")]
).process(raw)
```

CSV 文件在运行结束时写出；运行期间，各页会写入 `results.csv.journal`，如果某次运行崩溃，下一
次运行会重放它。请把 `*.journal` 加入 `.gitignore`，放在你的输出文件旁边。新文件的表头是
`record_id`、你的各列以及 `extra`，因此请新建一个文件，而不要让导出器指向由
`AsyncCsvUpsertExporter` 写入的文件；导出器会拒绝表头不同的文件。`AsyncJsonlExporter` 则为
每条记录写一行 JSON。

自定义导出器需实现 `write`；如果使用缓冲，则设置 `durable_writes = False` 并实现 `flush`：

```python
from sci_etl_core import AsyncExporter


class DatabaseExporter(AsyncExporter):
    def __init__(self, database):
        self.database = database

    async def write(self, record, entities):
        await self.database.replace_rows(record.record_id, list(entities))
```

`write` 必须是幂等的，因为崩溃可能导致某条记录被重复处理；没有实体的记录应当清除之前写入的
内容。只有当记录的实体已持久化时，它才会被标记为已处理：在 `write` 之后立即标记，或者在
`durable_writes` 为 `False` 时，在该页 `flush` 之后标记。`write` 故障会使该记录失败并计入一次
尝试，`flush` 故障会使该页已写入的记录保持未落定且不计入尝试，`open` 故障会在任何请求之前
中止运行。[运行语义](https://xueromll.github.io/sci-etl-core/latest/guide/run-semantics/)把
这些编号为 R20 至 R23。

`AsyncSqlTableExporter` 和 `AsyncPlotly3DExporter` 已被移除；请按[表格输出端](#table-sinks)
所示，使用 `sci_etl_core.processors.sinks` 中的 `SqlTableSink` 和 `Plotly3DSink`。
`ScatterPlotConfig` 从 `sci_etl_core.processors` 导入。

### 实体提取器是类型化的，并能感知记录 {#entity-extractors-are-typed-and-record-aware}

`AsyncEntityExtractor` 在实体类型上是泛型的，流水线调用 `extract_record(record, text)`，其
默认实现调用 `extract(text)`。只重写了 `extract` 的提取器无需修改。包装另一个提取器的包装层
也应委托 `extract_record`，这样它在包装需要记录的提取器（例如 `AsyncLLMClaimExtractor`）时
仍能正常工作：

```python
from sci_etl_core import AsyncEntityExtractor


class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(self, inner, validator):
        self.inner = inner
        self.validator = validator
        self.requires_record = inner.requires_record

    async def extract(self, text):
        return [entity for entity in await self.inner.extract(text) if self.validator.is_valid(entity)]

    async def extract_record(self, record, text):
        entities = await self.inner.extract_record(record, text)
        return [entity for entity in entities if self.validator.is_valid(entity)]
```

这样的包装层通常已不再需要：`AsyncLLMEntityExtractor` 接受 `validator`，会连同原因记录每次
拒绝，并且可以把被拒绝的实体保存在拒绝记录存储中。`system_prompt` 之后的所有参数现在都只能
以关键字形式传入。

若要按 Pydantic 模型校验实体并得到模型实例，请传入 `schema=`；参见
[类型化实体与校验](https://xueromll.github.io/sci-etl-core/latest/guide/typed-entities/)。
包装另一个客户端的自定义 `AsyncLLMClient` 应转发 `complete_structured`，并在 `invalidate`
中接受 `schema=`。

### 校验器会说明原因 {#validators-say-why}

`RecordValidator.validate(entity)` 返回一个由 `Violation` 组成的 `ValidationResult`。只实现
了 `is_valid` 的校验器仍可使用。已经能计算原因的校验器（例如有 `rejection_reason` 方法）可以
改为重写 `validate`，这样原因就会进入日志和拒绝记录存储：

```python
from sci_etl_core.processors import RecordValidator, ValidationResult, Violation


class RangeValidator(RecordValidator):
    def is_valid(self, record):
        return self.validate(record).ok

    def validate(self, record):
        radius = record.get("radius_kpc")
        if radius is not None and not 0.1 <= float(radius) <= 20.0:
            violation = Violation(code="out-of-range", field="radius_kpc", severity="error", message=f"radius {radius} kpc")
            return ValidationResult(violations=(violation,))
        return ValidationResult()
```

### 日志通过 `logging` 模块输出 {#logging-goes-through-the-logging-module}

所有 `logger=` 参数都已移除：涉及 `AsyncETLPipeline`、`ETLPipeline`、四个提取器、
`AsyncLLMEntityExtractor`、`CachingLLMClient`、`AsyncCompositeIngestor`、
`AsyncHybridSearcher` 和 `ShutdownSignal`。`configure_logging` 和 `sci_etl_core.log_utils`
已被移除，`AsyncETLPipeline.log` 也是如此。每个模块都以自己的名称在 `sci_etl_core` 记录器
之下输出日志，因此请在应用程序中配置日志：

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler("output/pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
```

消息保持原有措辞。`CachingLLMClient` 过去把 `logger` 作为第四个位置参数；以位置方式传入它的
调用现在会因 `TypeError` 而失败。

### 已移除的名称 {#removed-names}

0.5 中的弃用项已被移除：阻塞式契约 `Extractor`、`StateManager`、`Exporter`、`LLMClient`、
`RelevanceFilter` 和 `EntityExtractor`；它们的适配器 `SyncExtractorAdapter`、
`SyncRelevanceFilterAdapter`、`SyncEntityExtractorAdapter`、`SyncExporterAdapter`、
`SyncStateManagerAdapter` 和 `SyncLLMClientAdapter`；`LegacyExtractorAdapter`；
`AsyncExporter.export` 和 `destination` 参数；`AsyncCsvUpsertExporter`、
`AsyncSqlTableExporter` 和 `AsyncPlotly3DExporter`；以及 `configure_logging`。请实现异步
契约，并在其中用 `asyncio.to_thread` 运行阻塞式工作。`ETLPipeline` 仍然保留，并像以前一样
从阻塞式代码运行异步流水线。

自 0.6 起，已弃用的名称在被移除之前至少还能在两个次版本中使用。

## 升级到 0.5.1 {#upgrading-to-051}

0.5.1 不会破坏任何现有调用，但有三种过去会让记录落定的 LLM 结果，现在会让记录失败。该记录
保持未标记状态，其尝试计入 `max_attempts`，并在下一次运行时重试：

- **空回复。** `AsyncOpenAICompatibleClient.complete_json` 会抛出 `LLMError`，而不再返回
  `{}`。
- **没有实体列表的响应。** 当响应为空，或有多个键但都不是 `result_key` 时，
  `AsyncLLMEntityExtractor.extract` 会抛出 `LLMError`，而不再返回 `[]`。
- **`default_on_error=False` 时的相关性故障。** `AsyncLLMRelevanceFilter` 和
  `AsyncEmbeddingRelevanceFilter` 会抛出异常，而不再把故障解读为“不相关”（那样会把记录永久
  标记为已处理）。

如果你的模型有时会回复空对象，或者把实体列表放在别的键下，这些记录现在会失败，并在
`max_attempts` 次运行后被隔离。请在提示词中写明 `result_key`。自定义的 `AsyncLLMClient` 遇到
无法读取的响应时应抛出 `LLMError`，而不是返回 `{}`。

早期版本以这种方式标记为已处理的记录仍保持已标记状态；只有使用全新状态的运行才会重新访问
它们。

LLM 缓存也有变化：

- **每个已缓存的响应都会未命中一次。** 缓存键现在包含端点的 `base_url`、温度和响应格式，
  因此升级后的第一次运行会为每个请求调用 LLM。早期版本写入的条目永远不会再被读取；请删除缓存
  文件或调用 `clear()` 以回收空间。不再需要在模型名中编码温度（例如 `"gpt-4o-mini@t0.2"`）。
- **被拒绝的响应会被删除。** `AsyncLLMEntityExtractor` 和 `AsyncLLMRelevanceFilter` 在拒绝
  某个响应时会调用其客户端的 `invalidate`，`CachingLLMClient` 随即删除该响应，因此重试会真正
  请求模型。自定义的 `AsyncLLMResponseCache` 应实现 `delete`。包装另一个客户端的自定义客户端
  应把 `invalidate` 转发给它。

## 升级到 0.5 {#upgrading-to-05}

0.5 改变了提取器的分页方式、状态保存的内容以及流水线的构造方式。实体和导出器在 0.6 中变化。
请要求新的次版本以及 Python 3.11：

```text
sci-etl-core[async,llm,pdf]>=0.5.0,<0.6
```

0.4 写入的状态无需转换。`AsyncSqliteStateManager` 会就地升级其数据库，
`AsyncFileStateManager` 会读取旧的元数据文件，并在下次保存时以新格式改写它。无论哪种情况，
保存的偏移量都会变成游标，因此下一次运行会从上一次停下的地方继续。

### 提取器返回已解析的页面 {#extractors-return-parsed-pages}

`search` 和 `parse_listing` 被单个 `fetch_page` 取代，它返回一个 `ListingPage`。流水线现在
会自行跳过已处理的记录，因此提取器应返回它能读取的每个条目。按偏移量分页的来源还要实现
`cursor_for_offset`，这使它成为 `OffsetListing`。

迁移前：

```python
class MyExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return await self._client.get_page(query, start_index, max_results)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        entries = parse(raw_listing)
        return [entry for entry in entries if entry.record_id not in seen_ids], len(entries)
```

迁移后：

```python
class MyExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = int(cursor or 0)
        entries = parse(await self._client.get_page(query, offset, page_size))
        return ListingPage(
            records=tuple(entries),
            entries=len(entries),
            next_cursor=str(offset + len(entries)) if entries else None,
        )
```

使用不透明续传令牌的来源把令牌作为 `next_cursor` 返回，并且不实现 `cursor_for_offset`。在
自身结果上限处停止的来源，在到达上限的那一页返回 `truncated=True` 和 `next_cursor=None`。在
提取器移植完成之前，`LegacyExtractorAdapter(MyOldExtractor())` 可以在 0.5.x 中原样运行它，并
发出 `DeprecationWarning`；0.6 移除了该适配器。

转发给另一个提取器的包装层（例如记录进度的包装层）要转发 `fetch_page`；当它包装的是
`OffsetListing` 时，还要转发 `cursor_for_offset`：

```python
class LoggingExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return self._inner.cursor_for_offset(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self._log(f"Fetching listing page at cursor {cursor or 'start'}")
        return await self._inner.fetch_page(query, cursor, page_size)
```

`newest_first=True` 和大于 0 的 `start_index` 需要 `OffsetListing`，否则会在任何请求之前
抛出 `ValueError`。`AsyncArxivExtractor`、`AsyncPubMedExtractor` 和
`AsyncSemanticScholarExtractor` 都是 `OffsetListing`。`AsyncOpenAlexExtractor` 现在使用
OpenAlex 游标分页，因此可以越过前 10,000 篇作品，但不再支持 `newest_first`；它在 0.5 上的
第一次运行会从第一页重新开始列表一次，因为 0.4 保存的偏移量不是 OpenAlex 游标。

### 状态保存的内容 {#what-the-state-saves}

`PipelineMetadata.cursor` 取代了 `last_start_index`。读取已保存位置的代码应读取游标；对于
`OffsetListing`，游标是十进制偏移量：

```python
metadata = await state.load_metadata()
saved_offset = int(metadata.cursor or 0)
```

进度事件新增了 `cursor`。对于 `OffsetListing`，`RunStarted.start_index`、
`PageFetched.offset` 和 `PageFinished.offset` 仍保存列表偏移量，对于其他任何提取器则为
`None`。

### 有上限的列表会重新开始 {#capped-listings-start-over}

PubMed 在 9,999 条结果处停止，Semantic Scholar 在 1,000 条处停止。在 0.4 中，到达上限的运行
会把上限保存为偏移量，之后的每次运行都会立即在那里结束。在 0.5 中，到达上限的那一页会以
`"completed"` 结束运行，由 `RunMetrics.listing_truncated` 报告，并重置保存的游标，因此下一次
运行会重新翻阅可访问的结果：已处理的记录按 id 跳过，因此重新扫描只消耗列表请求，不消耗 LLM
调用。请缩小查询范围（例如按日期）来避免重新扫描。

### 持续失败的记录会被隔离 {#records-that-keep-failing-are-quarantined}

在 3 次运行中都失败、且每次失败所在的页面都处理了其他记录的记录，会从下一次运行开始作为被
隔离的记录跳过，并计入 `RunMetrics.quarantined`。在没有处理任何记录的页面上的失败（例如服务
中断期间或 API 密钥被拒绝时）永远不会被计数。如需保留 0.4 的行为，即永远重试每条失败的
记录：

```python
await pipeline.run(query, page_size=100, total_limit=500, max_attempts=None)
```

第三方状态管理器无需修改即可继续使用：新增的 `record_failure` 和 `failure_counts` 都有不做任何
跟踪的默认实现，因此它永远不会隔离记录。

### 关键字参数 {#keyword-arguments}

`AsyncETLPipeline` 和 `ETLPipeline` 以位置或名称接收五个协作组件，其他所有参数都只能以关键字
形式传入。`run` 接收 `query`，之后只接受关键字参数，并且 `max_records=` 已被移除：

```python
pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    exporter,
    state_manager,
    destination="results.csv",
    max_concurrency=4,
)
await pipeline.run("all:galaxy", page_size=50, total_limit=200)
```

`RawRecord`、`PipelineMetadata`、`TokenUsage`、`RunMetrics` 以及各事件都只接受关键字参数，
因此 `RawRecord("id", "title", "abstract")` 要改为
`RawRecord(record_id="id", title="title", abstract="abstract")`。

### 严格的配置部分 {#strict-config-sections}

内置配置部分未声明的键现在会导致校验失败，并在 `ConfigurationError` 中被指出，因此
`search.bm25.titel` 之类的拼写错误或旧键 `pipeline.max_records` 不再能悄悄通过。请把
`pipeline.max_records` 改名为 `total_limit`，把 `pipeline.max_workers` 改名为
`max_concurrency`。暂时必须接受未知键的应用程序可以在其配置类上选择退出，每个被丢弃的键都会
以 `UserWarning` 报告：

```python
class AppConfig(BaseAppConfig):
    strict_sections = False
```

应用程序定义的顶层部分仍像以前一样保留。

### 表格输出端 {#table-sinks}

`AsyncSqlTableExporter` 和 `AsyncPlotly3DExporter` 接收的是 `DataFrame`，无法在流水线中运行。
它们的替代者是用于后处理输出的阻塞式输出端：

```python
from sci_etl_core.processors.sinks import Plotly3DSink, ScatterPlotConfig, SqlTableSink

catalogue = chain.process(raw_table)
SqlTableSink("sqlite:///catalogue.db", "galaxies", if_exists="replace").write(catalogue)
Plotly3DSink(ScatterPlotConfig("x", "y", "z", color_column="size"), "catalogue.html").write(catalogue)
```

### 0.6 之前没有替代品的弃用项 {#deprecations-with-no-replacement-before-06}

以下名称在 0.5.x 中仍可使用，并发出 `PendingDeprecationWarning` 而不是 `DeprecationWarning`，
因为它们的替代品在 0.6 中才提供，目前还没有什么需要修改：`destination` 参数、
`AsyncExporter.export` 和 `AsyncCsvUpsertExporter`（由导出器生命周期和 `AsyncCsvExporter`
取代），以及每个 `logger=` 参数和 `configure_logging`（由标准 `logging` 模块取代）。因此，
使用 `-W error::DeprecationWarning` 运行的测试套件在使用它们时仍能通过。

阻塞式契约及其 `Sync*Adapter`、`LegacyExtractorAdapter` 以及两个表格导出器会发出
`DeprecationWarning`，因为它们的替代品在 0.5 中已经存在；请迁移到每个组件都已实现的异步
契约、`fetch_page` 以及表格输出端。

`build_retrying_session` 已被移除，`full` extra 不再安装 `requests`。

## 升级到 0.4 {#upgrading-to-04}

```text
sci-etl-core[async]>=0.4.0,<0.5
```

0.4 新增了来源、解析器、LLM 响应缓存、优雅关闭、进度事件、速率限制器和检索功能。以下变更会
影响现有代码：

- **改名的流水线设置。** `pipeline.max_records` 现在是 `total_limit`，
  `pipeline.max_workers` 现在是 `max_concurrency`。旧的 YAML 键以及
  `PipelineConfig.max_records` 和 `max_workers` 属性在 0.5 之前仍可使用，并发出
  `DeprecationWarning`；`run(max_records=)` 也以同样方式弃用。请在配置文件中改掉这两个键的
  名称。
- **更多流水线设置。** `PipelineConfig` 现在有 `page_size`、`search_delay` 和
  `newest_first`。只添加了这些字段的子类可以删除。
- **无需包装层的校验。** `AsyncLLMEntityExtractor` 接受 `validator=`、`logger=` 和
  `label_field=`，并把丢弃的每个实体记录为 `Entity rejected by validation: <label>`。只为了
  应用 `RecordValidator` 而包装它的提取器可以删除。
- **根据配置构建组件。** `AsyncArxivExtractor.from_config`、
  `AsyncOpenAICompatibleClient.from_config` 和 `AsyncETLPipeline.from_config` 读取 `http`、
  `llm` 和 `pipeline` 部分，`config.http.build_client()` 取代了 `build_async_client`，
  `config.pipeline.run_arguments()` 返回 `run()` 的参数，因此不再需要手动把设置复制到构造
  函数中。
- **最新优先的续跑。** `run(newest_first=True)` 无需 `start_index=0` 那样的完整重新扫描即可
  获取 arXiv 新投稿，并把列表头部保存在元数据文件中 `last_start_index` 的旁边。不能与
  `start_index` 一起使用。
- **绘图。** `ScatterPlotConfig` 接受 `hover_data_columns`、`hover_template`、
  `color_continuous_scale` 和 `color_range`，覆盖了过去需要手动构建图形才能实现的自定义悬停
  文本和固定颜色范围。
- **截断与表格布局。** `ValueClipStep` 在后处理期间截断列值，`TableLayoutStep` 对行排序并
  调整列顺序，可以替代实现这两种功能的项目专用处理器。
- **从已有的记忆中检索。** 已在 `AsyncSqliteEmbeddingStore` 中存储了文本块的项目，可以用
  `backfill_text_index` 根据这些文本块构建文本索引，而无需重新获取每篇论文。
- **语义命中结果的摘要片段。** 仅由语义分支找到的 `FusedHit` 现在带有其最佳文本块的摘要
  片段，而过去它的 `snippet` 是空的。过去在 `snippet` 为空时显示摘要的界面，应改为检查
  `lexical_rank is None`。
- **已弃用的 `requests` 辅助函数。** `build_retrying_session` 会发出警告，并将在 0.5 中与
  `full` extra 中的 `requests` 一起被移除。

## 升级到 0.3 {#upgrading-to-03}

```text
sci-etl-core[async]>=0.3.0,<0.4
```

0.3 新增了本地检索和发现图。以下变更会影响现有代码：

- **arXiv 记录带有元数据。** `RawRecord.metadata` 现在包含 `categories`、`authors`、
  `published` 和 `year`，而不再为空。你自己读取记录的代码（包括比较 `metadata == {}` 的测试）
  会看到这些新键。与嵌入文本块一同存储的元数据保持不变。
- **`memory_ingestor` 接受任何 `MemoryIngestor`。** `AsyncChunkIngestor` 的工作方式与以前
  完全相同。你代码中为该参数标注 `AsyncChunkIngestor` 的类型提示可以放宽为
  `MemoryIngestor`。
- **检索需要主动启用。** 不传入文本索引的流水线不会有任何变化。要添加文本索引，请按照
  [本地检索与发现](https://xueromll.github.io/sci-etl-core/latest/guide/search/)所示，传入
  一个 `AsyncSearchIndexer`，或者一个把分块摄取器放在第一位的 `AsyncCompositeIngestor`。它的
  `AsyncSqliteFts5Store` 与其他 SQLite 存储一样放进 `closeables`。
- **SQLite 状态在取消时更安全。** `AsyncSqliteStateManager` 不再让被取消操作的工作线程与下一
  个操作重叠。`AsyncFileStateManager` 保持不变。

升级中有疑问，或遇到了不顺手的地方？请提交一个
[issue](https://github.com/xueromll/sci-etl-core/blob/master/.github/ISSUE_TEMPLATE/bug_report.md)，
我们乐意提供帮助。
