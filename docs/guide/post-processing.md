# Post-processing and visualization

## The exporters

The pipeline writes each processed record's entities to its exporter, with
the record they came from, and a record with no entities too. Two exporters
are bundled, and neither merges, coerces, or clips a value, so a conflict
between papers stays visible until you decide how to resolve it.

**`AsyncCsvExporter(path, columns)`** writes one row per entity. The first
column is `record_id`, then the `columns` you name, then `extra`, which holds
every other key of the entity as a JSON object. Values are written as the
model returned them, so `"3.2 ± 0.4"` stays text and `2.9` stays `2.9`.
Writing a record again replaces all of its rows. The file is rendered once,
when the run ends; during the run each page is appended to
`<path>.journal`, which a crashed run leaves behind and the next run replays
before anything else. An existing file must be UTF-8 and have the same
header, or the run aborts before its first request instead of overwriting it.
On Windows, the final rename is retried for about a second and a half while
another program holds the file open.

Cells a spreadsheet would run as a formula (starting with `=`, `+`, `-`, `@`,
a tab, or a carriage return) are written with a leading apostrophe, which the
exporter strips again when it reloads the file; other tools reading the CSV
see it. Plain numbers such as `-5.361` or `+1e8` are written unchanged, so
pandas and spreadsheets read them as numbers. Pass `escape_formulas=False` to
write every cell unchanged.

**`AsyncJsonlExporter(path)`** appends one JSON line per written record, with
its `record_id`, `title`, `source_url`, and `entities`. A record written again
appends another line, and `read_jsonl_export(path)` keeps the last line for
each record. Use it when entities are nested or you want the paper's title and
link next to them.

Both accept entities as dicts, Pydantic models, dataclass instances, or
claims. To keep evidence and provenance in a queryable store instead, write
claims to an `AsyncClaimStoreExporter`; see [Claims and provenance](claims.md).

## Cleaning and plotting

Cleanup, deduplication, scoring, and plots are a separate step over a
DataFrame. The exporter's table has one row per paper and entity, so this is
where you choose how rows about the same object from different papers become
one:

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
        NormalizationStep("name", DefaultKeyNormalizer()),  # adds _norm_key
        DeduplicationStep("_norm_key"),                     # one row per key
        CompletenessStep(["value_a", "value_b"]),           # adds completeness_pct
        QualityFlagStep(),                                  # adds quality_flag
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

`pd.to_numeric(..., errors="coerce")` turns text such as `"3.2 ± 0.4"` into
an empty cell, so decide first whether such values need parsing instead.
`DeduplicationStep` keeps the first row of each key and fills its empty cells
from the others, so sort the rows first when one source should win. Pass
`source_column="record_id"` to add a `sources` column that lists every paper
merged into each row. The raw
table stays on disk as the record of what each paper reported. `clean` then
looks like this:

| _norm_key | name     | value_a | value_b | completeness_pct | quality_flag   |
|-----------|----------|---------|---------|------------------|----------------|
| objecta   | Object A | 12.4    | 0.87    | 100.0            | Confirmed      |
| objectb   | Object B | 9.1     |         | 50.0             | Needs Review   |
| objectc   | Object C |         |         | 0.0              | Low Confidence |

`Plotly3DSink` drops rows that are missing any axis value, writes nothing when
no row remains, and replaces the HTML file atomically. It needs the `viz`
extra when constructed; importing `sci_etl_core.processors.sinks` needs only
the `processors` extra. The sinks are blocking, so call `write` through
`asyncio.to_thread` from async code.

### Styling the plot

`ScatterPlotConfig` also controls hover text and colors:

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
  cells. Clamping hides an out-of-range value behind a plausible one, so
  prefer rejecting such values with a validator during extraction.
- **`TableLayoutStep(sort_by, leading_columns, hidden_prefixes)`** prepares a
  table for publishing: it sorts rows by `(column, ascending)` pairs with
  missing values last, drops helper columns such as `_norm_key` by prefix, and
  moves the `leading_columns` to the front.
- **Record validators** check individual entity dicts: `NumericRangeValidator`,
  `KeywordExclusionValidator`, and `CompositeValidator`. `validate(entity)`
  returns a `ValidationResult` whose `violations` name the field and the rule
  each rejection broke; `CompositeValidator` collects the violations of every
  validator it holds. Pass one to `AsyncLLMEntityExtractor(validator=...)` to
  drop invalid entities before export. Each rejection is logged with its
  reasons, labelled by the `label_field` value when you name one, and stored
  for review when you pass a rejection store as `rejections=`:

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

  A validator of your own subclasses `RecordValidator` and implements
  `is_valid`; override `validate` too, to report reasons other than
  "rejected".
- **`SqlTableSink(url, table_name)`** writes a DataFrame to a database
  through a synchronous SQLAlchemy URL, in one transaction, e.g.
  `SqlTableSink("sqlite:///results.db", "entities").write(clean)`. It needs
  the `sql` extra when constructed. Like `Plotly3DSink`, it takes a
  DataFrame, so use it after post-processing rather than as the pipeline's
  exporter.
