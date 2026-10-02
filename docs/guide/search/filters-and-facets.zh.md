# 过滤器与分面

元数据过滤器是与查询一起传入的 `MetadataFilter` 和 `RangeFilter` 值，绝不写在查询文本里。
存储会按其 `facet_keys` 中列出的元数据键为每个文档打上标签。每个内置提取器都会在
`RawRecord.metadata` 中填写 `categories` 和 `authors`，在来源提供日期时还会填写
`published` 和 `year`（每个来源额外添加的键见[支持的来源](../sources.md)），而
`AsyncSearchIndexer` 会把这些元数据复制到索引中。

```python
from sci_etl_core.search import MetadataFilter, RangeFilter, parse_query

filters = (
    MetadataFilter("categories", {"astro-ph.GA", "astro-ph.CO"}),
    RangeFilter("published", low="2020-01", high="2024-06"),
)
outcome = await searcher.search("dwarf galaxy", filters=filters)
facets = await text_store.facet_counts(["categories", "year"], query=parse_query("dwarf galaxy"), filters=filters)
```

- **匹配。** `MetadataFilter` 保留带有其任一值标签的记录；设置 `negated=True` 时则剔除
  它们。每个过滤器都必须通过。同一个键的多个值放在一个过滤器中：对同一个键使用两个过滤器
  （包括一个 `MetadataFilter` 加一个 `RangeFilter`），或使用不在 `facet_keys` 中的键，都会
  在任何 I/O 之前抛出 `ValueError`。
- **标签。** 字符串、整数及其列表会成为标签；其他值不会被打标签。某个键下有多个标签的记录
  （例如有多位作者），只要其中任一标签通过过滤器，该记录就通过。
- **在数量限制之前生效。** 过滤器在索引内部、在 `limit` 之前生效，并作用于混合检索的两条
  分支，因此被过滤掉的记录永远不会占用结果名额。`filter_graph` 也以同样方式把它们应用到
  发现图上。
- **分面计数。** `facet_counts` 把每个键映射为 `(value, count)` 对，先按计数、再按值排序，
  不含计数为零的项。每个键的计数会应用查询以及作用于*其他*键的所有过滤器，因此计数表示选择
  该值后会得到多少结果，且被过滤键的其他值仍然可见。`query=None` 对整个索引计数。
- **修改 `facet_keys`。** 这些键在构造存储时确定，并记录在文件中。要修改它们，请用新的键
  构造存储，然后执行 `await text_store.rebuild_tags()`。在此之前，对尚未建立标签的键进行
  过滤或分面会抛出 `SearchStoreError`。

## 范围 {#ranges}

`RangeFilter` 保留标签位于 `low` 和 `high` 之间的记录。两个边界都是闭区间，任一边界都可以
省略；设置 `negated=True` 时则改为剔除范围内的记录。边界的类型决定标签如何比较：

| 边界 | 比较方式 | 示例 | 保留 |
|------|----------|------|------|
| 整数 | 按数值 | `RangeFilter("year", 2020, 2024)` | 从 `2020` 到 `2024` 的标签，无论以整数还是文本存储 |
| 文本 | 按文本，`high` 与相同数量的开头字符比较 | `RangeFilter("published", "2024-01", "2024-06")` | 从 `2024-01-01` 到 `2024-06-30T23:59:59Z` |

- **整数。** 只有按 Python 书写整数的方式写出的标签才能落入整数范围：`2024`、`0` 和 `-3`
  可以，而 `"07"`、`"+3"` 和 `"2024-05-01"` 永远不会。整数边界适合计数类数据（例如引用
  次数），这类数据按文本比较会排错顺序。
- **文本。** 文本逐字符比较，因此 ISO 8601 日期和四位数年份能正确排序。由于 `high` 只与标签
  的开头字符比较，`high="2024-06"` 会保留 2024 年 6 月的所有日期，`high="2024"` 会保留
  2024 年的所有日期。
- **无效范围。** 没有任何边界的范围、空的文本边界、`bool` 或 `float` 类型的边界、一个整数
  边界加一个文本边界，或者 `low` 大于 `high`（因而不可能匹配任何内容），都会在构造时抛出
  异常。

## 范围计数 {#counting-ranges}

`range_counts` 统计每个范围内的匹配记录数，可用于直方图的分桶或“近 5 年”之类的预设。与
`facet_counts` 一样，每个计数都会应用查询以及作用于*其他*键的所有过滤器，因此选中某个分桶
后，其他分桶的计数仍然可见：

```python
from sci_etl_core.search import RangeFilter, parse_query

buckets = [RangeFilter("year", low, low + 4) for low in range(2000, 2025, 5)]
counts = await text_store.range_counts(buckets, query=parse_query("dwarf galaxy"), filters=filters)
for bucket, count in zip(buckets, counts):
    print(f"{bucket.low}–{bucket.high}: {count}")
```

计数按 `ranges` 的顺序以元组形式返回，各范围可以共用同一个键，也可以相互重叠。
`AsyncSqliteFts5Store` 在一次一致的读取中统计所有范围。自定义存储会继承一个按范围逐个调用
`filter_ids` 的实现。
