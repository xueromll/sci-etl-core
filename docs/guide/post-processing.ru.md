# Постобработка и визуализация

## Экспортёры {#the-exporters}

Пайплайн записывает сущности каждой обработанной записи в свой экспортёр
вместе с записью, из которой они получены, а также запись без сущностей. В
комплект входят два экспортёра, и ни один из них не объединяет, не приводит и
не обрезает значения, поэтому противоречие между статьями остаётся видимым,
пока вы не решите, как его разрешить.

**`AsyncCsvExporter(path, columns)`** пишет по одной строке на сущность.
Первый столбец — `record_id`, затем названные вами `columns`, затем `extra`,
где все остальные ключи сущности хранятся как объект JSON. Значения
записываются так, как их вернула модель, поэтому `"3.2 ± 0.4"` остаётся
текстом, а `2.9` остаётся `2.9`. Повторная запись записи заменяет все её
строки. Файл формируется один раз, когда запуск заканчивается; во время
запуска каждая страница дописывается в `<path>.journal`, который аварийно
завершившийся запуск оставляет после себя, а следующий запуск воспроизводит
его прежде всего остального. Существующий файл должен быть в UTF-8 и иметь тот
же заголовок, иначе запуск прерывается до первого запроса, а не перезаписывает
его. В Windows финальное переименование повторяется в течение примерно полутора
секунд, пока другая программа держит файл открытым.

Ячейки, которые электронная таблица выполнила бы как формулу (начинающиеся с
`=`, `+`, `-`, `@`, табуляции или возврата каретки), записываются с ведущим
апострофом, который экспортёр снова убирает при повторной загрузке файла;
другие инструменты, читающие CSV, его видят. Простые числа, такие как `-5.361`
или `+1e8`, записываются без изменений, поэтому pandas и электронные таблицы
читают их как числа. Передайте `escape_formulas=False`, чтобы записывать
каждую ячейку без изменений.

**`AsyncJsonlExporter(path)`** дописывает по одной строке JSON на каждую
записанную запись с её `record_id`, `title`, `source_url` и `entities`.
Повторно записанная запись добавляет ещё одну строку, а
`read_jsonl_export(path)` оставляет последнюю строку для каждой записи.
Используйте его, когда сущности вложены или когда вы хотите видеть рядом с
ними заголовок статьи и ссылку на неё.

Оба принимают сущности в виде словарей, моделей Pydantic, экземпляров
dataclass или утверждений. Чтобы вместо этого хранить доказательства и
происхождение в хранилище с запросами, записывайте утверждения в
`AsyncClaimStoreExporter`; см. [Утверждения и происхождение](claims.md).

## Очистка и построение графиков {#cleaning-and-plotting}

Очистка, дедупликация, оценка и графики — отдельный шаг над DataFrame. В
таблице экспортёра одна строка на пару «статья — сущность», поэтому именно
здесь вы решаете, как строки об одном и том же объекте из разных статей
становятся одной:

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
        NormalizationStep("name", DefaultKeyNormalizer()),  # добавляет _norm_key
        DeduplicationStep("_norm_key"),                     # одна строка на ключ
        CompletenessStep(["value_a", "value_b"]),           # добавляет completeness_pct
        QualityFlagStep(),                                  # добавляет quality_flag
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

`pd.to_numeric(..., errors="coerce")` превращает текст вроде `"3.2 ± 0.4"` в
пустую ячейку, поэтому сначала решите, не нужно ли такие значения разбирать.
`DeduplicationStep` оставляет первую строку каждого ключа и заполняет её пустые
ячейки из остальных, поэтому сначала отсортируйте строки, если один источник
должен побеждать. Передайте `source_column="record_id"`, чтобы добавить
столбец `sources` со списком всех статей, объединённых в каждую строку. Сырая
таблица остаётся на диске как запись того, что сообщила каждая статья.
`clean` тогда выглядит так:

| _norm_key | name     | value_a | value_b | completeness_pct | quality_flag   |
|-----------|----------|---------|---------|------------------|----------------|
| objecta   | Object A | 12.4    | 0.87    | 100.0            | Confirmed      |
| objectb   | Object B | 9.1     |         | 50.0             | Needs Review   |
| objectc   | Object C |         |         | 0.0              | Low Confidence |

`Plotly3DSink` отбрасывает строки, в которых нет значения хотя бы по одной оси,
ничего не пишет, если не осталось ни одной строки, и атомарно заменяет файл
HTML. При создании ему нужен extra `viz`; импорт
`sci_etl_core.processors.sinks` требует только extra `processors`. Стоки
блокирующие, поэтому из асинхронного кода вызывайте `write` через
`asyncio.to_thread`.

### Оформление графика {#styling-the-plot}

`ScatterPlotConfig` также управляет всплывающими подсказками и цветами:

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

- **`hover_data_columns`** становятся `%{customdata[0]}`, `%{customdata[1]}`
  и так далее в `hover_template`, в порядке перечисления; имя в подсказке —
  `%{hovertext}`.
- **`color_continuous_scale`** и **`color_range`** фиксируют цвета числового
  столбца цвета, так что значение имеет один и тот же цвет в каждом экспорте.
  `color_label` задаёт заголовок цветовой шкалы или легенды для
  категориального столбца цвета.
- **`marker`** обновляет маркеры каждой трассы, а **`layout`** применяется к
  макету фигуры последним, поэтому перекрывает `template` и поля по умолчанию.

## Другие строительные блоки {#other-building-blocks}

- **`ClusteringStep(feature_extractor)`** запускает DBSCAN по признакам,
  которые возвращает ваш собственный `FeatureExtractor`.
- **`ValueClipStep(bounds)`** ограничивает числовые столбцы диапазонами,
  например `{"fraction": (0.0, 1.0)}`, превращая нечисловые значения в пустые
  ячейки. Ограничение прячет значение вне диапазона за правдоподобным, поэтому
  лучше отвергать такие значения валидатором во время извлечения.
- **`TableLayoutStep(sort_by, leading_columns, hidden_prefixes)`** готовит
  таблицу к публикации: сортирует строки по парам `(column, ascending)`, ставя
  пропуски в конец, удаляет вспомогательные столбцы, такие как `_norm_key`, по
  префиксу и переносит `leading_columns` в начало.
- **Валидаторы записей** проверяют отдельные словари сущностей:
  `NumericRangeValidator`, `KeywordExclusionValidator` и `CompositeValidator`.
  `validate(entity)` возвращает `ValidationResult`, `violations` которого
  называют поле и правило, нарушенные каждым отклонением; `CompositeValidator`
  собирает нарушения всех входящих в него валидаторов. Передайте его в
  `AsyncLLMEntityExtractor(validator=...)`, чтобы отбрасывать некорректные
  сущности до экспорта. Каждое отклонение записывается в журнал вместе с
  причинами, помеченное значением `label_field`, если вы его указали, и
  сохраняется для проверки, если вы передадите хранилище отклонений как
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

  Собственный валидатор наследует `RecordValidator` и реализует `is_valid`;
  переопределите также `validate`, чтобы сообщать причины, отличные от
  «rejected».
- **`SqlTableSink(url, table_name)`** записывает DataFrame в базу данных через
  синхронный URL SQLAlchemy в одной транзакции, например
  `SqlTableSink("sqlite:///results.db", "entities").write(clean)`. При
  создании ему нужен extra `sql`. Как и `Plotly3DSink`, он принимает
  DataFrame, поэтому используйте его после постобработки, а не как экспортёр
  пайплайна.
