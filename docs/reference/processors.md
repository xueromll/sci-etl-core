# Processors

Every name on this page is importable from `sci_etl_core.processors`.

::: sci_etl_core.processors.base

::: sci_etl_core.processors.normalization

::: sci_etl_core.processors.dedup

::: sci_etl_core.processors.clustering

::: sci_etl_core.processors.quality

::: sci_etl_core.processors.validation

::: sci_etl_core.processors.shaping

The table sinks need the `processors` extra, and `SqlTableSink` and `Plotly3DSink` also need `sql` and
`viz` when constructed. `ScatterPlotConfig` and `render_scatter_3d` are imported from
`sci_etl_core.processors.sinks`.

::: sci_etl_core.processors.sinks
