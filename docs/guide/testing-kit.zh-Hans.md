# 测试你的组件

`sci_etl_core.testing` 包含契约测试套件：按照基类契约检查组件行为的 pytest
测试类。为你的组件继承对应的套件，添加一个构建该组件的 fixture，pytest
就会针对你的实现运行套件中的每个测试。内置实现运行的是同样的套件。

| 套件 | 检查对象 | 针对的内置实现 |
|------|----------|----------------|
| `ExtractorContract` | `AsyncExtractor` | `AsyncArxivExtractor`、`AsyncPubMedExtractor`、`AsyncSemanticScholarExtractor`、`AsyncOpenAlexExtractor` |
| `StateManagerContract` | `AsyncStateManager` | `AsyncFileStateManager`、`AsyncSqliteStateManager` |
| `ExporterContract` | `AsyncExporter` | `AsyncJsonlExporter`、`AsyncCsvExporter`、`AsyncClaimStoreExporter` |
| `EmbeddingStoreContract` | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`、`AsyncSqliteEmbeddingStore` |

## 安装 {#installing}

这些套件需要 pytest，由 `testing` extra 安装：

```bash
pip install "sci-etl-core[testing]"
```

库中的其他模块都不导入 pytest。测试是普通函数，每个场景都通过 `asyncio.run`
运行，因此不需要 pytest-asyncio。

## 编写契约测试 {#writing-a-contract-test}

在测试模块中以 pytest 会收集的名称继承套件，并为它提供套件所需的
fixture。下面是一个把状态保存在内存中的状态管理器运行 `StateManagerContract`
的例子：

```python
import dataclasses

import pytest

from sci_etl_core import AsyncStateManager, PipelineMetadata
from sci_etl_core.testing import StateManagerContract


class MemoryStateManager(AsyncStateManager):
    def __init__(self) -> None:
        self._processed: set[str] = set()
        self._metadata = PipelineMetadata()

    async def load_processed_ids(self) -> set[str]:
        return set(self._processed)

    async def mark_processed(self, record_id: str) -> None:
        self._processed.add(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return dataclasses.replace(self._metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        self._metadata = dataclasses.replace(metadata)


class TestMemoryStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self):
        manager = MemoryStateManager()
        return lambda: manager
```

现在 `python -m pytest` 会针对 `MemoryStateManager` 运行套件中的每个测试。
套件类本身不会被收集，因为它的名称不以 `Test` 开头。

fixture 返回一个工厂：一个不接受参数的可调用对象，每次调用都返回一个基于同一
存储的新实例，就像流水线的每次运行打开它一样。套件会在一个测试中多次调用它，
以检查一个实例保存的内容能被下一个实例加载。像上面那样把状态保存在内存中的
组件，每次都返回同一个实例。每个测试开始时存储都是空的，因此请基于 `tmp_path`
或在 fixture 内部构建它。套件在运行中的事件循环内调用工厂，并像一次运行结束
那样结束每个实例：状态管理器先写回状态，有 `aclose()` 时再用它关闭；导出器或
向量存储则被关闭。

## Fixture {#fixtures}

| 套件 | 必需的 fixture | 可选的 fixture |
|------|----------------|----------------|
| `ExtractorContract` | `make_extractor` | `make_unavailable_extractor` |
| `StateManagerContract` | `make_state_manager` | `write_newer_schema` |
| `ExporterContract` | `make_exporter`、`read_exported` | `make_entities`、`write_newer_schema` |
| `EmbeddingStoreContract` | `make_store` | `write_newer_schema` |

- **`make_extractor`、`make_state_manager`、`make_exporter` 和
  `make_store`** 返回上面描述的工厂。
- **`read_exported`** 返回一个异步可调用对象，它接受一个记录 id，返回目标为该
  记录保存的实体，没有时返回空序列。套件会比较两次读取的结果，因此请返回一种
  在内容相同时比较相等的形式。
- **`make_entities`** 返回一个可调用对象，为一条记录构建 `count` 个不同的实体。
  默认构建带有 `name` 和 `value` 键的字典；当你的导出器接受其他实体（例如论断）
  时，请重写它。
- **`write_newer_schema`** 返回一个可调用对象，它向工厂打开的存储中写入一个
  模式版本比你的组件所支持的更新的文件或数据库。套件在创建实例之前调用它，并
  期望得到 `SciEtlError`。默认返回 `None`。
- **`make_unavailable_extractor`** 返回一个提取器工厂，该提取器的来源对每个
  请求都以服务器端故障（例如状态 `503`）应答，且重试之间不等待。套件期望得到
  `UpstreamError`，而不是空页。默认返回 `None`。

同一个状态管理器套件针对内置的 SQLite 状态管理器运行时，还会检查来自更新版本
的数据库是否被拒绝：

```python
import sqlite3
from contextlib import closing

import pytest

from sci_etl_core import AsyncSqliteStateManager
from sci_etl_core.testing import StateManagerContract


class TestSqliteStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: AsyncSqliteStateManager(tmp_path / "state.db")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        def write():
            with closing(sqlite3.connect(tmp_path / "state.db")) as connection:
                connection.execute("PRAGMA user_version = 99")

        return write
```

导出器还需要 `read_exported`，用来读回它的目标：

```python
import pytest

from sci_etl_core.exporters import AsyncJsonlExporter, read_jsonl_export
from sci_etl_core.testing import ExporterContract


class TestJsonlExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncJsonlExporter(tmp_path / "out.jsonl", fsync=False)

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            return read_jsonl_export(tmp_path / "out.jsonl").get(record_id, [])

        return read
```

## 离线测试提取器 {#testing-an-extractor-offline}

提取器套件从不访问网络。请用桩提供列表，例如基于 `httpx.MockTransport` 构建的
`httpx.AsyncClient`，并让它对同一个请求每次都给出相同的应答。列表必须为套件的
查询提供至少两页，并在 `max_pages` 页之内结束。请在子类中按你的来源设置这些
类属性：

| 属性 | 默认值 | 含义 |
|------|--------|------|
| `query` | `"contract"` | 每个测试列出的查询 |
| `page_size` | `2` | 每个测试请求的页大小 |
| `max_pages` | `50` | 列表结束前最多允许的页数 |

## 可选能力与跳过 {#optional-capabilities-and-skips}

检查可选能力的测试，在你的组件缺少该能力时会被跳过，并给出原因：

- **状态管理器：**失败的尝试，当 `record_failure` 保留什么都不记录的默认实现时；
  `forget`，当状态管理器不是 `Forgetting` 时；`aclose()` 之后的重用，当它没有
  `aclose` 时。
- **导出器：**在 `flush` 之前读取写入的内容，当 `durable_writes` 为 `False` 时。
- **向量存储：**`iter_records`，当存储保留抛出 `NotImplementedError` 的默认实现时。
- **提取器：**偏移量测试，当提取器不是 `OffsetListing` 时；不可用来源测试，当
  `make_unavailable_extractor` 返回 `None` 时。
- **状态管理器、导出器和向量存储：**模式版本测试，当 `write_newer_schema` 返回
  `None` 时。

## 套件检查什么 {#what-the-suites-check}

- **`ExtractorContract`：**第一页是带有记录和下一个游标、结构正确的
  `ListingPage`；下一个游标会再次返回同一页，从新的提取器请求也一样，就像续跑
  的运行那样请求；沿着下一个游标前进最终会结束列表，截断的页没有下一个游标；
  对于 `OffsetListing`，偏移量 0 就是第一页，第一页的条目数就是第二页的偏移量；
  `fetch_full_text` 返回字符串；无法访问的来源抛出 `UpstreamError`。
- **`StateManagerContract`：**新存储是空的；已处理的 id、保存的元数据和失败的
  尝试会延续到下一个实例；并发的标记全部保留；`save_metadata` 记录运行时间；
  `mark_processed` 清除记录的尝试；`forget` 清除标记和尝试并保留游标；模式版本
  更新的状态被拒绝；状态管理器在 `aclose()` 之后仍能工作。
- **`ExporterContract`：**一次运行导出每条记录的实体；重复写入（并发、在同一次
  运行中或在之后的运行中）留下的结果与一次写入相同；没有实体的记录不保存任何
  实体；没有写入的运行能成功完成；导出器在 `aclose()` 之后可以再次运行；当
  `durable_writes = True` 时，写入的内容在 `flush` 之前就可以读取；模式版本更新
  的目标被拒绝。
- **`EmbeddingStoreContract`：**新存储是空的；以相同记录 id 和索引再次添加的
  文本块会替换旧的；文本块会延续到下一个实例；命中结果按余弦相似度从好到差排列，
  并遵守 `top_k`、`min_score` 和 `exclude_record_id`；包含 NaN 的向量永远不会
  匹配；`delete_record` 和 `replace_record` 不会留下记录的任何旧文本块；
  `iter_records` 按顺序产出段落；存储在 `aclose()` 之后仍能工作；模式版本更新的
  存储被拒绝。

套件只通过公开方法检查行为。[契约表](../project/contributing.md#adding-a-new-component)
列出了每个组件必须做到的事，[测试 API 参考](../reference/testing.md)记录了每个
套件。
