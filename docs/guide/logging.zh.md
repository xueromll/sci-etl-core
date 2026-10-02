# 日志

sci-etl-core 的每个模块都通过标准 `logging` 模块输出日志，所用的记录器以模块名命名，例如
`sci_etl_core.pipeline_async` 或 `sci_etl_core.extractors.arxiv_async`。它们都位于
`sci_etl_core` 记录器之下。本库不安装任何处理器，也不设置任何级别，因此在应用程序配置
日志之前不会输出任何内容：

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("pipeline.log", encoding="utf-8"), logging.StreamHandler()],
)
logging.getLogger("sci_etl_core.extractors").setLevel(logging.WARNING)
```

各级别的含义如下：

| 级别 | 用于 |
|------|------|
| `ERROR` | 运行所报告的输出端或存储故障：导出器的 `flush` 或 `aclose` 失败、状态无法写回、资源无法关闭、事件处理器抛出异常 |
| `WARNING` | 会改变运行产出或成本的情况：记录失败或被跳过、记录被隔离、来源在其结果上限处停止或拒绝了游标、记忆后端出错、下载内容不可用、重试、关闭信号 |
| `INFO` | 例行说明：实体或论断未通过校验而被拒绝，`newest_first` 运行从何处续跑 |

消息沿用了早期版本传给 `logger=` 可调用对象的措辞，例如
`Record processing failed: LLMError('...')`，因此针对这些消息编写的过滤器或告警仍然能匹配。

[可观测性](observability.md)中的进度事件仍然是结构化的渠道：用事件统计记录、页面和结果，
用日志了解原因。
