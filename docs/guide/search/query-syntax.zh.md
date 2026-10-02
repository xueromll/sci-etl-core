# 查询语法

| 结构 | 示例 | 匹配 |
|------|------|------|
| 词项 | `galaxy` | 该词，忽略大小写和重音符号，因此 `Müller` 能匹配 `Muller` |
| 短语 | `"dwarf galaxy"` | 按顺序相邻出现的这些词 |
| 前缀 | `photometr*` | 任何以 `photometr` 开头的词 |
| 字段限定 | `title:quasar`、`title,abstract:"dwarf galaxy"` | 仅在指定字段中匹配：`title`、`abstract`、`body` |
| 邻近 | `NEAR(dwarf "dark matter" halo*, 5)`、`title:NEAR(dwarf halo)` | 同一字段中的所有词项和短语，彼此相距不超过 5 个 token（默认 10），顺序不限 |
| 与 | `a AND b`、`a && b`、`a b` | 两者都有 |
| 或 | `a OR b`、`a \|\| b` | 任一 |
| 非 | `NOT a`、`-a` | 不含 `a` 的文档 |
| 分组 | `(a OR b) -c` | |

`NOT` 的优先级最高，其次是 `AND`，然后是 `OR`。运算符必须大写，因此 `and` 是普通单词。
被分词器拆开的词（例如 `H-alpha`）会作为由其各部分组成的短语来检索。

## 邻近 {#proximity}

`NEAR(...)` 接受以空格分隔的词项、短语和前缀词项，之后可选地跟一个逗号和一个表示 token
数的整数。选取各次出现，使最后开始的那一个从第 `p` 个 token 开始，则其他每个操作数都必须
在 `p` 之前不超过该数量的 token 处结束：`NEAR(a b, 2)` 能匹配 `a x x b` 和 `b x a`，
但不能匹配 `a x x x b`。

- **限定整个分组，而不是其中的部分。** `abstract:NEAR(dwarf halo)` 在摘要中查找；把字段
  限定放在括号内（例如 `NEAR(title:dwarf halo)`）会引发 `SearchQueryError`。
- **分组内只能有词。** 分组内的 `AND`、`OR`、`NOT`、`-`、`&&`、`||` 和嵌套括号都会被拒绝。
  请改为对整个分组取反或组合，例如 `quasar -NEAR(dwarf halo, 3)`。
- **简写形式。** 只有一个操作数的分组（例如 `NEAR(dwarf)`）就等于该词项。只包含一个带引号
  短语的分组（例如 `NEAR("dwarf halo", 3)`）检索的是该短语中的词彼此邻近，而不是该短语
  本身。
- **大写且不带空格。** `NEAR` 必须大写，且后面紧跟 `(`；`near(a b)` 和 `NEAR (a b)` 会被
  解读为单词 `near` 以及词项 `a` 和 `b`。

`NEAR` 分组在两种文本存储中都像其他词项一样参与排序、过滤和高亮。在混合检索中，除了其中的
前缀词项外，它的词会像查询的其余部分一样被嵌入。`describe` 把一个分组返回为一个
`QueryChip`，其 `near` 是它的距离。

`AsyncSqliteFts5Store` 有一个例外：某些 SQLite 版本（包括 3.50.4）对于部分文档，无法高亮
位于 `OR` 或 `NOT` 内部、带字段限定的分组，例如 `dwarf OR title:NEAR(dwarf halo)` 或
`dwarf -title:NEAR(dwarf halo)`。此时检索会抛出注明 SQLite 版本的 `SearchQueryError`。
请去掉分组的字段限定，或者分别检索 `OR` 的每个分支。`filter_ids` 和内存存储不受影响。

## 解析 {#parsing}

解析是纯粹且同步的，因此查询栏可以在每次按键时运行它。格式错误的查询会抛出
`SearchQueryError`，其 `position` 和 `token` 指出错误所在；`describe` 则把解析出的词和
短语返回为 `QueryChip`，供界面显示：

```python
from sci_etl_core import SearchQueryError
from sci_etl_core.search import describe, parse_query

try:
    chips = describe(parse_query("title:quasar (blazar OR -dwarf"))
except SearchQueryError as exc:
    print(f"{exc} (column {exc.position}: {exc.token!r})")
```
