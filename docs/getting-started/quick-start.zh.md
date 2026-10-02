# 快速开始

本示例在 arXiv 中检索，询问 LLM 哪些论文相关，从这些论文的全文中提取测量值，并把它们写入
CSV，每个测量值一行。它需要 `async`、`arxiv`、`llm` 和 `pdf` extra，并从 `LLM_API_KEY`
环境变量读取 API 密钥，因此密钥永远不会出现在源代码中。若要改为从 `.env` 文件加载，请参阅
[配置](configuration.md)。

```python
import asyncio
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncETLPipeline,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
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


async def main() -> None:
    client = build_async_client()
    llm = AsyncOpenAICompatibleClient(
        api_key=os.environ["LLM_API_KEY"],
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    pipeline = AsyncETLPipeline(
        extractor=AsyncArxivExtractor(
            client=client,
            pdf_parser=PdfPlumberParser(),
            latex_parser=LatexTarballParser(),
        ),
        relevance_filter=AsyncLLMRelevanceFilter(
            llm_client=llm, system_prompt=RELEVANCE_PROMPT
        ),
        entity_extractor=AsyncLLMEntityExtractor(
            llm_client=llm, system_prompt=EXTRACTION_PROMPT
        ),
        exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
        state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
        max_concurrency=4,
        closeables=[client, llm],
    )

    async with pipeline:
        try:
            processed = await pipeline.run("all:galaxy", total_limit=50)
        except PipelineAborted as exc:
            print(f"Stopped early after {exc.partial_count} records: {exc}")
            return
    print(f"Processed {processed} relevant records")


asyncio.run(main())
```

## 一次运行做了什么 {#what-a-run-does}

1. 在状态管理器保存的游标处（或在 `start_index=0` 时从第一页开始）获取一个列表页
   （`page_size` 条记录，默认 100），并跳过已处理的记录。只包含已处理记录的页面会被越过，
   而不会被当作数据的结尾。
2. 对剩余的每条记录（同时最多 `max_concurrency` 条）：相关性过滤 → 获取全文 → 可选的记忆
   摄取 → 实体提取 → 写入导出器 → 标记为已处理。没有实体的记录也会被写入，以便导出器可以
   清除重新提取后不再出现的行。不相关的记录不获取全文，直接标记为已处理。`record_id` 缺失
   或为空的记录无法跟踪，因此会被跳过并记录日志。
3. 刷新导出器，使该页的行得到持久化；对于带缓冲的导出器（例如 `AsyncCsvExporter`），其记录
   直到这时才被标记为已处理。然后保存列表游标并重复上述过程，直到处理了 `total_limit` 条
   相关记录或列表结束；在获取后续每一页之前等待 `sleep_between` 秒（默认 0）。游标只会越过
   所有记录都已落定的页面；在 3 次运行中都失败的记录会作为被隔离的记录跳过；参见
   [状态、续跑与错误](../guide/state.md)。

`total_limit` 只统计**相关**记录，永远不会超出，默认等于 `page_size`。`run()` 中查询之后
的所有参数都只能以关键字形式传入。`max_concurrency` 和 `page_size` 必须至少为 1，
`total_limit` 不能为负；其他值会在发出任何请求之前抛出 `ValueError`。为遵守 arXiv 的速率
限制，`AsyncArxivExtractor` 还会在每次列表请求之前等待 `sleep_before_search` 秒（默认 3）。

无论运行如何结束，导出器都会被刷新并关闭：`AsyncCsvExporter` 在此时写出 `results.csv`，
并在运行期间维护一个 `results.csv.journal`。退出时，`async with pipeline` 会对
`closeables` 中每个具有 `aclose()` 的项执行 await：包括 HTTP 客户端、LLM 客户端，以及你所
使用的任何 `AsyncSqliteStateManager`、`AsyncSqliteEmbeddingStore` 或
`AsyncSqliteFts5Store`。

## 提示词必须要求返回 JSON {#prompts-must-ask-for-json}

`AsyncOpenAICompatibleClient` 会请求 JSON 模式（`response_format={"type": "json_object"}`），
而 OpenAI 的 API 会拒绝消息中从未提到 “JSON” 的 JSON 模式请求。本库读取的响应形式如下：

- `AsyncLLMRelevanceFilter` 读取 `relevant` 键。它接受布尔值、`0`/`1`，或者不区分大小写的
  字符串 `"true"`、`"false"`、`"yes"`、`"no"`、`"1"` 和 `"0"`。其他任何内容（包括缺少该键）
  都视为错误：该记录会通过；若设置了 `default_on_error=False`，过滤器则抛出 `LLMError`，
  该记录会被重试。
- `AsyncLLMEntityExtractor` 读取 `result_key`（默认 `"items"`）下的列表；如果响应恰好只有
  一个键，则读取该键唯一的值。列表必须包含对象；`null` 表示没有实体，单独一个对象算作一个
  实体。该处的其他任何值都会抛出 `LLMError`，从而重试该记录。空的回复，以及有多个键却没有
  `result_key` 的响应，也会抛出 `LLMError`，因此请在提示词中写明该键名。
- `AsyncCsvExporter` 把 `columns` 中列出的键写入各自的列，并把其他所有键以 JSON 形式写入
  `extra` 列，因此不会丢失任何值。把 Pydantic 模型作为 `schema=` 传入，即可校验每个实体；
  参见[类型化实体](../guide/typed-entities.md)。

## 后续步骤 {#next-steps}

- 使用 [`ETLPipeline`](blocking-usage.md) 从同步代码运行同一条流水线。
- 使用[类型化配置](configuration.md)从 YAML 和 `.env` 加载设置。
- 使用[论断与溯源](../guide/claims.md)保留每个值背后的论文和证据句。
- 使用[后处理步骤](../guide/post-processing.md)清洗 CSV 并绘图。
