# 阻塞式用法

`ETLPipeline` 是唯一的同步类。它接受与 `AsyncETLPipeline` 相同的参数（包括同样的
**异步**协作组件），另外还有 `run_timeout`：

```python
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    ETLPipeline,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

RELEVANCE_PROMPT = (
    "Decide whether the paper reports measurements of galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "Extract every measured object from the paper. Reply with JSON: "
    '{"items": [{"name": "...", "value_a": 0.0, "value_b": 0.0}]}.'
)

client = build_async_client()
llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
)

with ETLPipeline(
    extractor=AsyncArxivExtractor(
        client=client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
    ),
    relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
    entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
    exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
    closeables=[client, llm],
    run_timeout=3600,
) as pipeline:
    try:
        processed = pipeline.run(query="all:galaxy", total_limit=50)
    except PipelineAborted as exc:
        processed = exc.partial_count

print(f"Processed {processed} relevant records")
```

- **单个组件没有阻塞版本。** 若要从同步代码直接调用提取器、客户端或导出器，请把调用包装进
  一个协程，再用 `asyncio.run` 运行它。若要把阻塞代码接入流水线，请实现异步接口，并在其中用
  `asyncio.to_thread` 运行阻塞工作，内置的解析器和处理器就是这样被调用的。
- **`run_timeout`** 以秒为单位，默认不限时。超时后运行会被取消，并抛出 `TimeoutError`。
- **事件循环。** `ETLPipeline` 在一个共享的后台事件循环线程上运行流水线。它可以在普通脚本中
  使用，也可以在正在运行的事件循环内部（例如 notebook）调用。但它仍会阻塞调用线程直到运行
  结束，因此在异步代码中请改为 await `AsyncETLPipeline`。一旦某个协作组件被 `ETLPipeline`
  使用过，它就属于后台循环了，不要再从你自己的事件循环中使用它。
- **`with ETLPipeline(...)`** 在退出时关闭 `closeables`，每个资源最多允许 30 秒。
