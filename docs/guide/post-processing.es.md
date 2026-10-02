# Posprocesamiento y visualización

## Los exportadores {#the-exporters}

El pipeline escribe las entidades de cada registro procesado en su
exportador, junto con el registro del que proceden, y también un registro sin
entidades. Se incluyen dos exportadores, y ninguno fusiona, convierte ni
recorta un valor, así que un conflicto entre artículos sigue visible hasta que
decidas cómo resolverlo.

**`AsyncCsvExporter(path, columns)`** escribe una fila por entidad. La primera
columna es `record_id`, después las `columns` que indiques y luego `extra`, que
contiene el resto de las claves de la entidad como un objeto JSON. Los valores
se escriben tal como los devolvió el modelo, así que `"3.2 ± 0.4"` sigue siendo
texto y `2.9` sigue siendo `2.9`. Volver a escribir un registro reemplaza todas
sus filas. El archivo se genera una sola vez, cuando termina la ejecución;
durante la ejecución cada página se añade a `<path>.journal`, que una ejecución
que se cuelga deja atrás y que la siguiente reproduce antes que nada. Un
archivo existente debe estar en UTF-8 y tener la misma cabecera; si no, la
ejecución aborta antes de su primera solicitud en lugar de sobrescribirlo. En
Windows, el renombrado final se reintenta durante segundo y medio
aproximadamente mientras otro programa mantiene abierto el archivo.

Las celdas que una hoja de cálculo ejecutaría como fórmula (las que empiezan
por `=`, `+`, `-`, `@`, un tabulador o un retorno de carro) se escriben con un
apóstrofo inicial, que el exportador vuelve a quitar cuando recarga el
archivo; otras herramientas que lean el CSV lo verán. Los números simples como
`-5.361` o `+1e8` se escriben sin cambios, así que pandas y las hojas de
cálculo los leen como números. Pasa `escape_formulas=False` para escribir
todas las celdas sin cambios.

**`AsyncJsonlExporter(path)`** añade una línea JSON por cada registro escrito,
con su `record_id`, `title`, `source_url` y `entities`. Un registro escrito de
nuevo añade otra línea, y `read_jsonl_export(path)` conserva la última línea de
cada registro. Úsalo cuando las entidades estén anidadas o quieras el título y
el enlace del artículo junto a ellas.

Ambos aceptan entidades como diccionarios, modelos de Pydantic, instancias de
dataclass o afirmaciones. Para conservar en su lugar la evidencia y la
procedencia en un almacén consultable, escribe afirmaciones en un
`AsyncClaimStoreExporter`; consulta [Afirmaciones y procedencia](claims.md).

## Limpiar y graficar {#cleaning-and-plotting}

La limpieza, la deduplicación, la puntuación y los gráficos son un paso aparte
sobre un DataFrame. La tabla del exportador tiene una fila por artículo y
entidad, así que aquí es donde eliges cómo las filas sobre el mismo objeto
procedentes de distintos artículos pasan a ser una sola:

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
        NormalizationStep("name", DefaultKeyNormalizer()),  # añade _norm_key
        DeduplicationStep("_norm_key"),                     # una fila por clave
        CompletenessStep(["value_a", "value_b"]),           # añade completeness_pct
        QualityFlagStep(),                                  # añade quality_flag
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

`pd.to_numeric(..., errors="coerce")` convierte texto como `"3.2 ± 0.4"` en una
celda vacía, así que decide primero si esos valores necesitan análisis.
`DeduplicationStep` conserva la primera fila de cada clave y rellena sus celdas
vacías con las demás, así que ordena primero las filas cuando una fuente deba
prevalecer. Pasa `source_column="record_id"` para añadir una columna `sources`
que enumere todos los artículos fusionados en cada fila. La tabla sin procesar
queda en el disco como registro de lo que informó cada artículo. `clean` queda
entonces así:

| _norm_key | name     | value_a | value_b | completeness_pct | quality_flag   |
|-----------|----------|---------|---------|------------------|----------------|
| objecta   | Object A | 12.4    | 0.87    | 100.0            | Confirmed      |
| objectb   | Object B | 9.1     |         | 50.0             | Needs Review   |
| objectc   | Object C |         |         | 0.0              | Low Confidence |

`Plotly3DSink` descarta las filas a las que les falta algún valor de eje, no
escribe nada si no queda ninguna fila y reemplaza el archivo HTML de forma
atómica. Necesita el extra `viz` al construirse; importar
`sci_etl_core.processors.sinks` solo necesita el extra `processors`. Los
sumideros son bloqueantes, así que llama a `write` mediante
`asyncio.to_thread` desde código asíncrono.

### Dar estilo al gráfico {#styling-the-plot}

`ScatterPlotConfig` también controla el texto emergente y los colores:

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

- **`hover_data_columns`** pasan a ser `%{customdata[0]}`, `%{customdata[1]}`,
  etc., en `hover_template`, en el orden indicado; el nombre emergente es
  `%{hovertext}`.
- **`color_continuous_scale`** y **`color_range`** fijan los colores de una
  columna de color numérica, de modo que un valor tenga el mismo color en todas
  las exportaciones. `color_label` titula la barra de color, o la leyenda en el
  caso de una columna de color categórica.
- **`marker`** actualiza los marcadores de todas las trazas, y **`layout`** se
  aplica al diseño de la figura en último lugar, así que prevalece sobre
  `template` y los márgenes por defecto.

## Otros bloques de construcción {#other-building-blocks}

- **`ClusteringStep(feature_extractor)`** ejecuta DBSCAN sobre las
  características que devuelve tu propio `FeatureExtractor`.
- **`ValueClipStep(bounds)`** restringe las columnas numéricas a intervalos,
  como `{"fraction": (0.0, 1.0)}`, y convierte en celdas vacías los valores que
  no son números. Restringir esconde un valor fuera de rango tras uno
  plausible, así que es preferible rechazar esos valores con un validador
  durante la extracción.
- **`TableLayoutStep(sort_by, leading_columns, hidden_prefixes)`** prepara una
  tabla para publicarla: ordena las filas por pares `(column, ascending)` con
  los valores ausentes al final, elimina por prefijo las columnas auxiliares
  como `_norm_key` y lleva las `leading_columns` al principio.
- **Los validadores de registros** comprueban diccionarios de entidades
  individuales: `NumericRangeValidator`, `KeywordExclusionValidator` y
  `CompositeValidator`. `validate(entity)` devuelve un `ValidationResult` cuyas
  `violations` indican el campo y la regla que infringió cada rechazo;
  `CompositeValidator` reúne las infracciones de todos los validadores que
  contiene. Pasa uno a `AsyncLLMEntityExtractor(validator=...)` para descartar
  las entidades no válidas antes de exportarlas. Cada rechazo se registra con
  sus motivos, etiquetado con el valor de `label_field` cuando indicas uno, y
  se guarda para revisarlo cuando pasas un almacén de rechazos como
  `rejections=`:

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

  Un validador propio hereda de `RecordValidator` e implementa `is_valid`;
  sobrescribe también `validate` para informar de motivos distintos de
  "rejected".
- **`SqlTableSink(url, table_name)`** escribe un DataFrame en una base de datos
  mediante una URL síncrona de SQLAlchemy, en una sola transacción, por
  ejemplo `SqlTableSink("sqlite:///results.db", "entities").write(clean)`.
  Necesita el extra `sql` al construirse. Igual que `Plotly3DSink`, recibe un
  DataFrame, así que úsalo después del posprocesamiento y no como exportador
  del pipeline.
