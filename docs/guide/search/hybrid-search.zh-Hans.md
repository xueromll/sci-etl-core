# 混合检索

`AsyncHybridSearcher(text_store, finder).search(query, top_k, mode=..., filters=...)`
运行一条或两条检索分支：

| `mode` | 运行内容 | 没有 `finder` 时 |
|--------|----------|------------------|
| `"lexical"` | 在文本索引上运行 BM25 | 不受影响 |
| `"semantic"` | 向量记忆，按每篇文章最好的文本块为其打分 | 抛出 `SearchQueryError` |
| `"hybrid"`（默认） | 同时运行两者，然后融合两个排名 | 只运行词法分支，并报告 `skipped=("semantic",)` |

- **嵌入器看到的内容。** 语义分支嵌入的是查询中的词，而不是查询语法。运算符、字段限定、
  被否定的词项和前缀词项都会被去掉，因此 `quasar -dwarf` 会按 `quasar` 嵌入，
  `quasar OR blazar` 与 `quasar blazar` 相同。只由前缀词项组成的混合查询会跳过语义分支；
  在语义模式下则抛出 `SearchQueryError`。
- **降级和跳过的分支。** `SearchOutcome.degraded` 列出尝试运行但失败的分支。在混合模式下，
  `EmbeddingError` 会通过 `logger` 记录，并返回词法结果。`SearchOutcome.skipped` 列出没有
  可运行内容的分支。两种情况都要告知用户。词法分支的失败总是会被抛出，因为这意味着本地
  索引已损坏。
- **融合。** 倒数排名融合（reciprocal rank fusion）只读取每个列表的顺序，因此 BM25 依赖于
  语料库的分数尺度永远不会扭曲融合结果。当分数差距应当计入时，传入
  `strategy=normalized_score_fusion`；要为词法列表和语义列表（按此顺序）设置权重，传入
  `fusion=FusionParams(weights=(1.0, 2.0))`。
- **命中结果。** `FusedHit` 带有 `lexical_rank` 和 `semantic_rank`（对应分支未返回该结果时
  为 `None`）、`title`、`metadata`、`snippet`、`highlights` 和 `snippets`。请展示排名，
  切勿把融合分数显示为百分比。
- **摘要片段。** 词法分支返回的记录保留其词法摘要片段，每个匹配字段一个。仅由语义分支找到
  的记录会得到使其入选的那个文本块的摘要片段，查询词出现之处会被高亮，形式为一个字段为
  `"body"` 的 `Snippet`。该段落是按语义匹配的，因此可能没有任何高亮；可检查
  `lexical_rank is None` 为其加上标签（例如“相关段落”），或者改用
  `text_store.get_documents` 读取摘要。
- **候选池。** 每条分支在融合前获取 `HybridParams.candidate_pool` 条记录（默认 100，且不少
  于 `top_k`），因此在词法分支中排第 40、在语义分支中排第 3 的记录仍可能进入前 20。语义
  分支向向量记忆请求 `candidate_pool × chunk_pool_factor` 个文本块（默认因子为 5）。当长
  文章占满靠前的文本块、导致候选池不足时，请调高该因子。
