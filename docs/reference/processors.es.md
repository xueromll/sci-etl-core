# Procesadores

Todos los nombres de esta página se importan desde `sci_etl_core.processors`.

::: sci_etl_core.processors.base

::: sci_etl_core.processors.normalization

::: sci_etl_core.processors.dedup

::: sci_etl_core.processors.clustering

::: sci_etl_core.processors.quality

::: sci_etl_core.processors.validation

::: sci_etl_core.processors.shaping

Los sumideros de tablas necesitan el extra `processors`, y `SqlTableSink` y
`Plotly3DSink` necesitan además `sql` y `viz` al construirse. `ScatterPlotConfig`
y `render_scatter_3d` se importan desde `sci_etl_core.processors.sinks`.

::: sci_etl_core.processors.sinks
