# 进度事件与指标

每次流水线运行都会收集指标，并且可以在运行过程中报告进度。

## 运行指标 {#run-metrics}

无论最近一次运行如何结束，`pipeline.last_run_metrics` 都会返回它的 `RunMetrics`：

```python
from sci_etl_core import AsyncETLPipeline

pipeline = AsyncETLPipeline(..., usage_sources=[llm, embedder])
try:
    await pipeline.run(query="all:galaxy", total_limit=200, newest_first=True)
finally:
    metrics = pipeline.last_run_metrics
    print(
        f"{metrics.outcome}: {metrics.processed} processed, {metrics.irrelevant} irrelevant, "
        f"{metrics.failed} failed in {metrics.duration_seconds:.0f} s"
    )
```

| 字段 | 含义 |
|------|------|
| `pages`、`listed` | 获取的列表页数及其包含的条目数 |
| `processed`、`irrelevant`、`deferred`、`failed`、`skipped` | 按结果分类的记录数；`deferred` 记录因 `total_limit` 或关闭而等待下一次运行，`skipped` 记录没有 id |
| `entities_exported` | 交给导出器的实体数 |
| `memory_faults` | 已记录但未导致记录失败的记忆摄取故障数 |
| `quarantined` | 因在之前的运行中失败了 `max_attempts` 次而被跳过的列表记录，每次运行每条只计一次 |
| `listing_truncated` | 当来源在其结果上限处停止列表时为 `True` |
| `duration_seconds` | 运行的实际耗时 |
| `token_usage` | `usage_sources` 在本次运行中使用的 token；没有来源时为 `None` |
| `outcome` | `completed`、`aborted`、`interrupted`、`cancelled` 或 `failed` |

`usage_sources` 接受任何具有 `usage` 属性的对象，例如 `AsyncOpenAICompatibleClient`、
`AsyncOpenAIEmbedder` 或 `CachingLLMClient`。运行之前的用量会被减去，因此在多次运行之间
共享的客户端会分别报告每次运行。

## 进度事件 {#progress-events}

传入 `on_event`，即可在运行过程中接收来自 `sci_etl_core.observability` 的类型化事件：

```python
from sci_etl_core.observability import PageFinished, RecordFinished, RunFinished


def report(event):
    if isinstance(event, RecordFinished) and event.outcome == "failed":
        print(f"{event.record_id} failed after {event.duration_seconds:.1f} s: {event.error!r}")
    elif isinstance(event, PageFinished):
        print(f"page at {event.cursor or 'start'}: {event.metrics.processed} processed so far")
    elif isinstance(event, RunFinished):
        print(f"run {event.metrics.outcome}")


pipeline = AsyncETLPipeline(..., on_event=report)
```

| 事件 | 触发时机 |
|------|----------|
| `RunStarted(query, start_index, total_limit, newest_first, cursor)` | 第一次列表请求之前 |
| `PageFetched(offset, entries, new_records, cursor, truncated)` | 收到一个列表页；`new_records` 尚未处理，`truncated` 标记来源在其结果上限处停止的那一页 |
| `RecordFinished(record_id, title, outcome, duration_seconds, entities, error)` | 一条记录在本次运行中离开流水线 |
| `PageFinished(offset, duration_seconds, metrics, cursor)` | 一页中的所有记录都已完成；`metrics` 是截至此时的运行情况 |
| `RunFinished(metrics)` | 运行结束，无论以何种方式结束 |

`cursor` 是请求该页时使用的列表游标，第一页为 `None`。当提取器按偏移量分页时，
`start_index` 和 `offset` 以列表偏移量的形式保存同一位置，否则为 `None`。每个事件和
`RunMetrics` 都是只接受关键字参数的 dataclass。

处理器运行在事件循环上，因此要保持快速：把网络调用之类的慢操作交给队列。它抛出的异常会被
记录为 `Event handler failed: ...`，并且永远不会停止运行。`ETLPipeline` 接受相同的参数，
同样提供 `last_run_metrics`。
