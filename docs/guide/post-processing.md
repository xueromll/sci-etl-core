# Post-processing and visualization

## The CSV exporter

The pipeline's exporter receives each record's entities as a `list[dict]`, and
`AsyncCsvUpsertExporter` is the built-in exporter that accepts that shape. It
keeps one row per normalized key: later records only fill empty cells, value
columns are converted to floats (anything non-numeric becomes empty), and
optional `numeric_clip` bounds clamp them.

The exporter reads the existing file (which must be UTF-8) before its first
write. If that read fails, for example because of a different encoding or a
malformed row, the export raises and the file is left untouched instead of
being overwritten. On Windows, a write is retried for about a second and a
half while another program holds the file open.

Keys come straight from LLM output, so a key a spreadsheet would run as a
formula (starting with `=`, `+`, `-`, `@`, a tab, or a carriage return) is
written with a leading apostrophe. The exporter strips it again when it
reloads the file; other tools reading the CSV see it. Pass
`escape_formulas=False` to write keys unchanged.

## Cleaning and plotting

Cleanup, scoring, and plots are a separate step over a DataFrame:

```python
import asyncio

import pandas as pd

from sci_etl_core import AsyncPlotly3DExporter, ScatterPlotConfig
from sci_etl_core.processors import (
    CompletenessStep,
    DeduplicationStep,
    DefaultKeyNormalizer,
    NormalizationStep,
    ProcessorChain,
    QualityFlagStep,
)

frame = pd.read_csv("results.csv", dtype={"name": str})
clean = ProcessorChain(
    [
        NormalizationStep("name", DefaultKeyNormalizer()),  # adds _norm_key
        DeduplicationStep("_norm_key"),                     # one row per key
        CompletenessStep(["value_a", "value_b"]),           # adds completeness_pct
        QualityFlagStep(),                                  # adds quality_flag
    ]
).process(frame)

plot = AsyncPlotly3DExporter(
    ScatterPlotConfig(
        x_column="value_a",
        y_column="value_b",
        z_column="completeness_pct",
        color_column="quality_flag",
        hover_name_column="name",
        title="Corpus overview",
    )
)
asyncio.run(plot.export(clean, "overview.html"))
```

`clean` then looks like this:

| _norm_key | name     | value_a | value_b | completeness_pct | quality_flag   |
|-----------|----------|---------|---------|------------------|----------------|
| objecta   | Object A | 12.4    | 0.87    | 100.0            | Confirmed      |
| objectb   | Object B | 9.1     |         | 50.0             | Needs Review   |
| objectc   | Object C |         |         | 0.0              | Low Confidence |

The Plotly exporter drops rows that are missing any axis value.

### Styling the plot

`ScatterPlotConfig` also controls hover text and colors:

```python
from sci_etl_core import ScatterPlotConfig

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

- **`hover_data_columns`** become `%{customdata[0]}`, `%{customdata[1]}`, and
  so on in `hover_template`, in the order listed; the hover name is
  `%{hovertext}`.
- **`color_continuous_scale`** and **`color_range`** fix the colors of a
  numeric color column, so a value has the same color in every export.
  `color_label` titles the color bar, or the legend for a categorical color
  column.
- **`marker`** updates every trace's markers, and **`layout`** is applied to
  the figure layout last, so it overrides `template` and the default margins.

## Other building blocks

- **`ClusteringStep(feature_extractor)`** runs DBSCAN over features returned by
  your own `FeatureExtractor`.
- **`ValueClipStep(bounds)`** clamps numeric columns into ranges, such as
  `{"fraction": (0.0, 1.0)}`, turning values that aren't numbers into empty
  cells. It does during post-processing what the CSV exporter's `numeric_clip`
  does during export.
- **`TableLayoutStep(sort_by, leading_columns, hidden_prefixes)`** prepares a
  table for publishing: it sorts rows by `(column, ascending)` pairs with
  missing values last, drops helper columns such as `_norm_key` by prefix, and
  moves the `leading_columns` to the front.
- **Record validators** check individual entity dicts: `NumericRangeValidator`,
  `KeywordExclusionValidator`, and `CompositeValidator`. Pass one to
  `AsyncLLMEntityExtractor(validator=...)` to drop invalid entities before
  export; each rejection is logged through its `logger`, labelled by the
  `label_field` value when you name one:

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
      logger=print,
      label_field="name",
  )
  ```
- **`AsyncSqlTableExporter(table_name)`** writes a DataFrame to a SQLAlchemy
  async URL, e.g.
  `await AsyncSqlTableExporter("entities").export(clean, "sqlite+aiosqlite:///results.db")`.
  Like the Plotly exporter, it takes a DataFrame, so use it after
  post-processing rather than as the pipeline's exporter.
