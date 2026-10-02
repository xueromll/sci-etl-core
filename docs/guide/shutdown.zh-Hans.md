# 优雅关闭

把 `ShutdownSignal` 传给流水线后，SIGINT（Ctrl+C）或 SIGTERM 就能干净地停止一次运行：

```python
from sci_etl_core import AsyncETLPipeline, PipelineInterrupted
from sci_etl_core.signals import ShutdownSignal

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
    shutdown=ShutdownSignal(),
)

try:
    count = await pipeline.run(query="all:galaxy", total_limit=500)
except PipelineInterrupted as stopped:
    print(f"Stopped after {stopped.partial_count} records; the next run picks up the rest")
```

流水线在每次 `run()` 期间安装信号处理器，并在之后恢复原来的处理器。

- **第一个信号：** 不再开始新的记录。正在处理的记录会完成，导出器被刷新，刷新后已持久化的
  记录被标记为已处理；尚未开始的记录保持未标记状态，留给下一次运行。待处理的列表请求或页面
  之间的等待会立即取消。保存的游标不会越过被中断的那一页。导出器被关闭，状态被写回，
  `run()` 抛出带有已处理记录数的 `PipelineInterrupted`。
- **第二个信号：** 恢复原来的处理器并立即终止。
- **以编程方式停止：** `shutdown.request()` 以同样的方式停止运行，例如在 Web 处理函数或
  测试中调用。

`PipelineInterrupted` 是 `PipelineAborted` 的子类，因此现有的 `except PipelineAborted`
仍能捕获它。如果被中断的运行应当与失败的运行以不同方式退出，请先捕获
`PipelineInterrupted`。

## 同步流水线 {#the-synchronous-pipeline}

`ETLPipeline` 接受同样的 `shutdown` 参数。它的工作在后台事件循环上运行，因此处理器安装在
调用 `run()` 的线程上，并把请求转发给该循环。由于只有主线程能接收信号，请在主线程中调用
`run()`：

```python
from sci_etl_core import ETLPipeline
from sci_etl_core.signals import ShutdownSignal

with ETLPipeline(..., shutdown=ShutdownSignal()) as pipeline:
    pipeline.run(query="all:galaxy", total_limit=500)
```

## 刷新导出器和状态 {#flushing-the-exporter-and-state}

无论运行如何结束（完成、中止、中断或取消），每次运行最后都会刷新并关闭导出器，然后调用
状态管理器的 `flush()`。`AsyncCsvExporter` 在关闭时生成 CSV 文件，
`AsyncSqliteStateManager` 在 `flush()` 中为其预写日志做检查点。如果运行本身已经失败，
刷新或关闭时的故障会被记录而不是抛出，以免掩盖原始错误。

## 自定义处理器 {#handlers-of-your-own}

`shutdown.guard()` 为你自己的一段代码安装处理器。guard 可以嵌套，因此在该代码块内获得
同一信号的流水线在运行结束时会保留你的处理器。处理器只能从主线程安装；在其他线程中，
`guard()` 会记录一条消息且不安装任何处理器，而 `request()` 仍然有效。
