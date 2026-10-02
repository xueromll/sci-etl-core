# 处理器

本页中的所有名称都可以从 `sci_etl_core.processors` 导入。

::: sci_etl_core.processors.base

::: sci_etl_core.processors.normalization

::: sci_etl_core.processors.dedup

::: sci_etl_core.processors.clustering

::: sci_etl_core.processors.quality

::: sci_etl_core.processors.validation

::: sci_etl_core.processors.shaping

表格输出端需要 `processors` extra，而 `SqlTableSink` 和 `Plotly3DSink` 在构造时
还分别需要 `sql` 和 `viz`。`ScatterPlotConfig` 和 `render_scatter_3d` 从
`sci_etl_core.processors.sinks` 导入。

::: sci_etl_core.processors.sinks
