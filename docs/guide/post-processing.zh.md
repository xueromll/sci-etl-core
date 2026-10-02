# 后处理与可视化

## 导出器 {#the-exporters}

流水线会把每条已处理记录的实体连同其来源记录一起写入导出器，没有实体的记录也会写入。本库
内置两个导出器，二者都不会合并、转换或截断任何值，因此论文之间的冲突会一直保持可见，直到你
决定如何解决。

**`AsyncCsvExporter(path, columns)`** 每个实体写一行。第一列是 `record_id`，接着是你指定的
`columns`，然后是 `extra`，其中以 JSON 对象保存实体的其他所有键。值按模型返回的原样写入，
因此 `"3.2 ± 0.4"` 仍是文本，`2.9` 仍是 `2.9`。再次写入某条记录会替换它的所有行。文件只在
运行结束时生成一次；运行期间，每一页都会追加到 `<path>.journal`，崩溃的运行会留下这个文件，
下一次运行会先重放它。已存在的文件必须是 UTF-8 编码且表头相同，否则运行会在第一次请求之前
中止，而不会覆盖它。在 Windows 上，如果其他程序正打开着该文件，最后的重命名会重试约一秒半。

电子表格会当作公式执行的单元格（以 `=`、`+`、`-`、`@`、制表符或回车开头）会在开头加上一个
撇号写入，导出器重新加载文件时会再把它去掉；其他读取该 CSV 的工具会看到这个撇号。`-5.361` 或
`+1e8` 这样的普通数字会原样写入，因此 pandas 和电子表格会把它们读作数字。传入
`escape_formulas=False` 可以原样写入每个单元格。

**`AsyncJsonlExporter(path)`** 为每条写入的记录追加一行 JSON，包含其 `record_id`、`title`、
`source_url` 和 `entities`。再次写入的记录会追加新的一行，`read_jsonl_export(path)` 会为
每条记录保留最后一行。当实体是嵌套结构，或者你希望把论文标题和链接放在实体旁边时，请使用它。

两者都接受字典、Pydantic 模型、dataclass 实例或论断形式的实体。若想把证据和溯源信息保存在
可查询的存储中，请把论断写入 `AsyncClaimStoreExporter`；参见[论断与溯源](claims.md)。

## 清洗与绘图 {#cleaning-and-plotting}

清洗、去重、评分和绘图是在 DataFrame 上进行的单独一步。导出器的表格中每篇论文的每个实体
一行，因此正是在这里决定如何把来自不同论文、关于同一对象的多行合并为一行：

```python
import pandas as pd

from sci_etl_core.processors import (
    CompletenessStep,
    DeduplicationStep,
    DefaultKeyNormalizer,
    NormalizationStep,
    Plotly3DSink,
    ProcessorChain,
    QualityFlagStep,
)
from sci_etl_core.processors.sinks import ScatterPlotConfig

frame = pd.read_csv("results.csv", dtype={"record_id": str, "name": str}, keep_default_na=False, na_values=[""])
for column in ("value_a", "value_b"):
    frame[column] = pd.to_numeric(frame[column], errors="coerce")
clean = ProcessorChain(
    [
        NormalizationStep("name", DefaultKeyNormalizer()),  # 添加 _norm_key
        DeduplicationStep("_norm_key"),                     # 每个键一行
        CompletenessStep(["value_a", "value_b"]),           # 添加 completeness_pct
        QualityFlagStep(),                                  # 添加 quality_flag
    ]
).process(frame)

plot = Plotly3DSink(
    ScatterPlotConfig(
        x_column="value_a",
        y_column="value_b",
        z_column="completeness_pct",
        color_column="quality_flag",
        hover_name_column="name",
        title="Corpus overview",
    ),
    "overview.html",
)
plot.write(clean)
```

`pd.to_numeric(..., errors="coerce")` 会把 `"3.2 ± 0.4"` 这样的文本变成空单元格，因此请先
决定这类值是否需要解析。`DeduplicationStep` 保留每个键的第一行，并用其他行填补其空单元格，
因此当某个来源应当优先时，请先对行排序。传入 `source_column="record_id"` 可以添加一个
`sources` 列，列出合并到每一行中的所有论文。原始表格仍保留在磁盘上，作为每篇论文所报告内容
的记录。`clean` 看起来如下：

| _norm_key | name     | value_a | value_b | completeness_pct | quality_flag   |
|-----------|----------|---------|---------|------------------|----------------|
| objecta   | Object A | 12.4    | 0.87    | 100.0            | Confirmed      |
| objectb   | Object B | 9.1     |         | 50.0             | Needs Review   |
| objectc   | Object C |         |         | 0.0              | Low Confidence |

`Plotly3DSink` 会丢弃缺少任一坐标轴值的行，没有剩余行时不写任何内容，并以原子方式替换
HTML 文件。它在构造时需要 `viz` extra；导入 `sci_etl_core.processors.sinks` 只需要
`processors` extra。输出端是阻塞式的，因此在异步代码中请通过 `asyncio.to_thread` 调用
`write`。

### 设置图表样式 {#styling-the-plot}

`ScatterPlotConfig` 还控制悬停文本和颜色：

```python
from sci_etl_core.processors.sinks import ScatterPlotConfig

config = ScatterPlotConfig(
    x_column="x",
    y_column="y",
    z_column="z",
    color_column="dark_matter_fraction",
    size_column="radius",
    hover_name_column="name",
    hover_data_columns=["constellation", "distance"],
    hover_template=(
        "<b>%{hovertext}</b><br>Constellation: %{customdata[0]}<br>"
        "Distance: %{customdata[1]} Mpc<extra></extra>"
    ),
    color_continuous_scale="Viridis",
    color_range=(0.0, 1.0),
    color_label="DM fraction",
    marker={"sizemode": "diameter", "sizemin": 3},
    layout={"paper_bgcolor": "#0b0f19", "scene": {"aspectmode": "cube"}},
)
```

- **`hover_data_columns`** 按列出的顺序成为 `hover_template` 中的 `%{customdata[0]}`、
  `%{customdata[1]}` 等；悬停名称为 `%{hovertext}`。
- **`color_continuous_scale`** 和 **`color_range`** 固定数值型颜色列的配色，使同一个值在每次
  导出中颜色相同。`color_label` 设置色条的标题；对于分类型颜色列，则设置图例的标题。
- **`marker`** 更新每条轨迹的标记，**`layout`** 最后应用到图形布局上，因此会覆盖
  `template` 和默认边距。

## 其他构建模块 {#other-building-blocks}

- **`ClusteringStep(feature_extractor)`** 在你自己的 `FeatureExtractor` 返回的特征上运行
  DBSCAN。
- **`ValueClipStep(bounds)`** 把数值列限制在指定范围内，例如 `{"fraction": (0.0, 1.0)}`，
  并把非数值变成空单元格。截断会用一个看似合理的值掩盖超出范围的值，因此更推荐在提取期间
  用校验器拒绝这类值。
- **`TableLayoutStep(sort_by, leading_columns, hidden_prefixes)`** 为发布准备表格：按
  `(column, ascending)` 对排序（缺失值排在最后），按前缀删除 `_norm_key` 之类的辅助列，并把
  `leading_columns` 移到最前面。
- **记录校验器**检查单个实体字典：`NumericRangeValidator`、`KeywordExclusionValidator` 和
  `CompositeValidator`。`validate(entity)` 返回一个 `ValidationResult`，其 `violations` 指出
  每次拒绝所违反的字段和规则；`CompositeValidator` 汇集它所包含的每个校验器的违规项。把校验器
  传给 `AsyncLLMEntityExtractor(validator=...)`，即可在导出前丢弃无效实体。每次拒绝都会连同
  原因记录到日志；如果你指定了 `label_field`，日志会用该字段的值作标签；如果你通过
  `rejections=` 传入拒绝记录存储，拒绝还会被保存以供复核：

  ```python
  from sci_etl_core import AsyncLLMEntityExtractor
  from sci_etl_core.processors import CompositeValidator, KeywordExclusionValidator, NumericRangeValidator

  extractor = AsyncLLMEntityExtractor(
      llm_client,
      system_prompt,
      validator=CompositeValidator(
          [
              KeywordExclusionValidator("name", ["simulation", "mock"]),
              NumericRangeValidator({"ra": (0.0, 360.0)}),
          ]
      ),
      label_field="name",
  )
  ```

  自定义校验器需继承 `RecordValidator` 并实现 `is_valid`；如需报告 “rejected” 以外的原因，
  还要重写 `validate`。
- **`SqlTableSink(url, table_name)`** 通过同步的 SQLAlchemy URL，在一个事务中把 DataFrame
  写入数据库，例如 `SqlTableSink("sqlite:///results.db", "entities").write(clean)`。它在
  构造时需要 `sql` extra。与 `Plotly3DSink` 一样，它接受的是 DataFrame，因此请在后处理之后
  使用它，而不要把它当作流水线的导出器。
