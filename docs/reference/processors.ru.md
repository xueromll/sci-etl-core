# Процессоры

Все имена на этой странице импортируются из `sci_etl_core.processors`.

::: sci_etl_core.processors.base

::: sci_etl_core.processors.normalization

::: sci_etl_core.processors.dedup

::: sci_etl_core.processors.clustering

::: sci_etl_core.processors.quality

::: sci_etl_core.processors.validation

::: sci_etl_core.processors.shaping

Табличным приёмникам нужен extra `processors`, а `SqlTableSink` и `Plotly3DSink`
при создании требуют также `sql` и `viz`. `ScatterPlotConfig` и
`render_scatter_3d` импортируются из `sci_etl_core.processors.sinks`.

::: sci_etl_core.processors.sinks
