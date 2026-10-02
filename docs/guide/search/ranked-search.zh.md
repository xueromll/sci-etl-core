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
