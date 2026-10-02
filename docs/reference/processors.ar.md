# المعالِجات

يمكن استيراد كل الأسماء في هذه الصفحة من `sci_etl_core.processors`.

::: sci_etl_core.processors.base

::: sci_etl_core.processors.normalization

::: sci_etl_core.processors.dedup

::: sci_etl_core.processors.clustering

::: sci_etl_core.processors.quality

::: sci_etl_core.processors.validation

::: sci_etl_core.processors.shaping

تحتاج مصارف الجداول إلى الإضافة `processors`، ويحتاج `SqlTableSink` و`Plotly3DSink`
كذلك إلى `sql` و`viz` عند إنشائهما. ويُستورد `ScatterPlotConfig` و`render_scatter_3d`
من `sci_etl_core.processors.sinks`.

::: sci_etl_core.processors.sinks
