# 排序检索与过滤

各存储接受已解析的查询，而 `AsyncHybridSearcher` 接受文本，并在任何 I/O 之前解析一次。
排序检索需要一个用于排序的词项，因此所有词项都被否定的查询（例如 `NOT simulation` 或
`NOT simulation OR quasar`）会使 `search` 抛出 `SearchQueryError`。这时请改用
`filter_ids`。它接受任何查询，并返回记录 id 的 `frozenset`；集合不带顺序，因此不会被
误当成排名：

```python
from sci_etl_core.search import parse_query

hits = await text_store.search(parse_query("photometr* dwarf"), limit=20)
observational = await text_store.filter_ids(parse_query("NOT simulation"))
```

`TextHit` 有一个 `score`，数值越高越好。它的尺度取决于语料库，因此只应在同一个结果列表内
比较分数。

## 摘要片段 {#snippets}

命中结果的 `snippet` 是来自匹配最好的字段的纯文本，`highlights` 保存匹配词在其中的
`[start, end)` 字符偏移量，由界面自行添加标记。超过 24 个 token 的字段会被截取为匹配处
周围 24 个 token 的窗口，省略的文本处用 `…` 表示。

当查询在多个字段中匹配时，`snippets` 按 `title`、`abstract`、`body` 的顺序为每个字段
保存一个 `Snippet`，因此一个结果可以同时显示标题中的匹配和正文中的段落：

```python
from sci_etl_core.search import parse_query

for hit in await text_store.search(parse_query("dwarf OR photometr*"), limit=10):
    for snippet in hit.snippets:
        marked = [snippet.text[start:end] for start, end in snippet.highlights]
        print(f"{hit.record_id} {snippet.field}: {snippet.text} {marked}")
```

只有当某个字段中有匹配词被高亮时，该字段才会出现在 `snippets` 中。两种文本存储高亮的词
相同，例外是某些查询中 FTS5 还会计入查询里未能匹配的部分中的词，`InMemoryTextSearchStore`
的文档说明了这种情况。

`passage_snippet(query, text)` 以同样方式为任意其他文本构建 `Snippet`，高亮查询中每个
未被否定的词。混合检索器用它来处理语义分支找到的段落。

## 对候选池排序 {#ranking-a-pool}

`rank` 接受与 `search` 相同的参数，并以相同的顺序、相同的分数返回相同的命中结果，但可能让
它们的摘要片段、高亮、标题和元数据留空。`hydrate` 为你要展示的命中结果补全这些内容，因此
对一个大的候选池排序时，无需为其中每个命中结果计算摘要片段：

```python
from sci_etl_core.search import parse_query

query = parse_query("dwarf galaxy")
pool = await text_store.rank(query, limit=500)
page = await text_store.hydrate(query, pool[:20])
```

- **开销。** `AsyncSqliteFts5Store` 只用 `bm25()` 排序，仅在 `hydrate` 中计算摘要片段并
  读取标题和元数据，因此对 500 个命中结果排序的开销只比对 20 个略多。它的 `search` 也在
  一次读取内以同样方式工作：先排序，只为返回的命中结果计算摘要片段。`AsyncHybridSearcher`
  用 `rank` 对其候选池排序，只对展示的命中结果调用 `hydrate`。
- **两次调用之间。** `hydrate` 读取调用那一刻的索引。如果某个命中结果的记录在 `rank` 之后
  被删除或不再匹配，该命中结果会按传入时的原样返回；在此期间重新索引的记录会得到其新文本
  的摘要片段。
- **自定义存储**会继承一个调用 `search` 的 `rank`，以及一个原样返回命中结果的 `hydrate`，
  这对任何存储都是正确的；要在不计算摘要片段的情况下排序，请同时重写这两个方法。
