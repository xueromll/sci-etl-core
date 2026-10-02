# 论断与溯源

论断是从论文中提取的一个值或一句陈述，与其来源论文、读取它的句子以及生成它的模型、提示词和
模式一起存储。借助论断，表格可以为每个值回答“是哪篇论文说的？”，可以把相互矛盾的报告并列
保存，也可以找出修正提示词后必须重新提取的所有值。

!!! note "临时性 API"
    `sci_etl_core.claims` 是 0.6.0 新增的临时性 API：在有已知使用方依赖它之前，名称可能
    在次版本中变化，并在 CHANGELOG 中记录。

## 提取论断 {#extracting-claims}

`AsyncLLMClaimExtractor` 向模型请求 `ClaimDraft` 对象，校验它们，在发送给模型的文本中定位
每份草稿的引文，然后返回 `Claim` 对象。`AsyncClaimStoreExporter` 逐条记录地保存它们：

```python
import os

from sci_etl_core import AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.claims import (
    AsyncClaimStoreExporter,
    AsyncLLMClaimExtractor,
    AsyncSqliteClaimStore,
    AsyncSqliteRejectionStore,
)

CLAIM_PROMPT = (
    "List every measurement of an ultra-diffuse galaxy in the paper. Reply with JSON: "
    '{"claims": [{"kind": "measurement", "subject": "...", "predicate": "effective_radius", '
    '"quantity": {"verbatim": "2.9 kpc", "value": 2.9, "unit_text": "kpc"}, '
    '"context": {"band": "g"}, "quote": "the sentence, copied exactly"}]}.'
)

llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"], base_url="https://api.openai.com/v1", model="gpt-4o-mini"
)
claims = AsyncSqliteClaimStore("data/claims.db")
rejections = AsyncSqliteRejectionStore("data/rejections.db")

pipeline = AsyncETLPipeline(
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=AsyncLLMClaimExtractor(llm, CLAIM_PROMPT, rejections=rejections),
    exporter=AsyncClaimStoreExporter(claims),
    state_manager=state_manager,
    closeables=[llm, claims, rejections],
)
```

继承 `ClaimDraft` 可以针对你的领域收窄 `predicate` 或 `context` 的键，然后把子类作为
`schema=` 传入。模型从不提供 id、偏移量或溯源信息；这些都由代码计算。

## 论断包含的内容 {#what-a-claim-holds}

| 字段 | 含义 |
|------|------|
| `claim_id` | 由记录、类型、主语、谓词、宾语、极性、上下文、数量的原文、文本片段和模式哈希计算出的摘要 |
| `kind` | `"measurement"`（需要 `quantity`）或 `"assertion"`（需要 `object`） |
| `subject`、`predicate`、`object` | 论断所涉及的内容，采用论文中的叫法 |
| `quantity` | 论文中书写的数值：`verbatim`、`value`、`unit_text`、`qualifier`、`uncertainty` |
| `statistics` | 效应量、置信区间界限、*p* 值、检验统计量、组样本量，均为可选 |
| `context` | 波段或样本等条件，以排序后的键值对表示 |
| `span` | `record_id`、找到引文的那一句或几句的起止偏移量，以及引文本身 |
| `stamp` | 模型、提示词哈希、模式哈希和库版本 |

模型、提示词和库版本是有意不计入 `claim_id` 的：用另一个模型重新提取同一篇论文时，只要字段
一致，就会得到相同的 id，只是标记是新的。主语按原样精确比较，因此 `"DF44"` 和 `"DF 44"` 是
不同的论断；名称归一化是之后的步骤，并且从不改写论断。`Claim.to_row()` 给出一个扁平的
映射，也就是存储以及 CSV 和 JSON Lines 导出器所写入的形式。

## 文本定位 {#grounding}

`locate_quote(text, quote)` 在发送给模型的文本中查找引文：先在合并空白后精确匹配，否则用
`difflib` 以不低于 `min_ratio`（0.9）的相似度做模糊匹配，并把匹配结果扩展到完整的句子。
句子切分器了解科学文体：`et al.`、`Fig. 3`、`Eq. (2)`、`i.e.`、`R.A.` 和小数都不会结束
一个句子。找不到引文的草稿视为未定位：它会被记录到日志，以代码 `"ungrounded"` 存入拒绝记录
存储，并且不会被返回。

## 存储 {#stores}

`InMemoryClaimStore` 和 `AsyncSqliteClaimStore` 遵循同一套契约：

- `replace_record(record_id, claims)` 在一个事务中替换某条记录的论断，并返回新的修订号。
  空列表会清空该记录，重新提取一无所获时正是如此，因为流水线会写入每条已处理的记录。
- `claims_for_records(record_ids)` 按存储顺序读回论断。
- `changes_since(revision)` 按修订号分页列出变更；修订号只增不减，因此下游任务可以从上次
  停下的地方继续。

SQLite 存储按记录、按 `(subject, predicate, object)`、按上下文键值对以及按规范化的类型和值
为论断建立索引，并记录自身的模式版本，因此之后版本的 sci-etl-core 能够打开由 0.6.0 写入的
文件。

`AsyncClaimStoreExporter.write` 中的存储故障会导致该记录失败，并像任何失败的记录一样在下一次
运行时重试、计为一次尝试。这不属于记忆故障。
