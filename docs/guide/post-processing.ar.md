# المعالجة اللاحقة والتصوير البياني

## المصدِّرات {#the-exporters}

يكتب خط المعالجة كيانات كل سجل معالَج إلى مصدِّره، مع السجل الذي جاءت منه، ويكتب كذلك
السجل الذي لا كيانات له. وتضم المكتبة مصدِّرين، لا يدمج أيٌّ منهما قيمة ولا يحوّلها ولا
يقتطعها، فيبقى التعارض بين الأوراق ظاهرًا حتى تقرر كيف تحلّه.

**`AsyncCsvExporter(path, columns)`** يكتب صفًا لكل كيان. العمود الأول هو `record_id`،
ثم `columns` التي تسمّيها، ثم `extra` الذي يحمل كل مفتاح آخر للكيان في صورة كائن JSON.
وتُكتب القيم كما أعادها النموذج، فيبقى `"3.2 ± 0.4"` نصًا ويبقى `2.9` كما هو `2.9`.
وكتابة السجل مرة أخرى تستبدل كل صفوفه. ويُكتب الملف مرة واحدة عند انتهاء التشغيل؛ وأثناء
التشغيل تُلحق كل صفحة بالملف `<path>.journal`، الذي يخلّفه التشغيل المنهار ويعيد التشغيل
التالي تطبيقه قبل أي شيء آخر. ويجب أن يكون الملف الموجود بترميز UTF-8 وبالترويسة نفسها،
وإلا أُجهض التشغيل قبل أول طلب بدلًا من الكتابة فوقه. وفي ويندوز تُعاد محاولة إعادة
التسمية الأخيرة نحو ثانية ونصف ما دام برنامج آخر يُبقي الملف مفتوحًا.

الخلايا التي قد ينفّذها برنامج جداول بيانات بوصفها صيغة (التي تبدأ بـ `=` أو `+` أو `-`
أو `@` أو علامة جدولة أو رجوع إلى أول السطر) تُكتب مسبوقة بفاصلة عليا، يزيلها المصدِّر
مجددًا عند إعادة تحميل الملف؛ أما الأدوات الأخرى التي تقرأ ملف CSV فتراها. والأعداد
البسيطة مثل `-5.361` أو `+1e8` تُكتب دون تغيير، فتقرؤها pandas وبرامج الجداول أعدادًا.
مرّر `escape_formulas=False` لكتابة كل خلية دون تغيير.

**`AsyncJsonlExporter(path)`** يُلحق سطر JSON واحدًا لكل سجل مكتوب، فيه `record_id`
و`title` و`source_url` و`entities`. والسجل المكتوب مرة أخرى يُلحق سطرًا آخر، وتحتفظ
`read_jsonl_export(path)` بآخر سطر لكل سجل. استخدمه حين تكون الكيانات متداخلة أو حين
تريد عنوان الورقة ورابطها بجوارها.

يقبل كلاهما الكيانات في صورة قواميس أو نماذج Pydantic أو نسخ من أصناف البيانات أو
ادعاءات. ولحفظ الأدلة والمصدر في مخزن قابل للاستعلام بدلًا من ذلك، اكتب الادعاءات إلى
`AsyncClaimStoreExporter`؛ راجع [الادعاءات ومصدرها](claims.md).

## التنظيف والرسم {#cleaning-and-plotting}

التنظيف وإزالة التكرار والتقييم والرسوم خطوة منفصلة تجري على DataFrame. ففي جدول
المصدِّر صف لكل ورقة وكيان، وهنا تختار كيف تصبح الصفوف المتعلقة بالجرم نفسه من أوراق
مختلفة صفًا واحدًا:

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
        NormalizationStep("name", DefaultKeyNormalizer()),  # يضيف _norm_key
        DeduplicationStep("_norm_key"),                     # صف واحد لكل مفتاح
        CompletenessStep(["value_a", "value_b"]),           # يضيف completeness_pct
        QualityFlagStep(),                                  # يضيف quality_flag
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

تحوّل `pd.to_numeric(..., errors="coerce")` نصًا مثل `"3.2 ± 0.4"` إلى خلية فارغة، فقرر
أولًا ما إذا كانت هذه القيم تحتاج إلى تحليل بدلًا من ذلك. ويُبقي `DeduplicationStep` أول
صف لكل مفتاح ويملأ خلاياه الفارغة من الصفوف الأخرى، فرتّب الصفوف أولًا حين ينبغي أن يغلب
مصدر بعينه. مرّر `source_column="record_id"` لإضافة عمود `sources` يسرد كل ورقة دُمجت في
كل صف. ويبقى الجدول الخام على القرص سجلًا لما أبلغت عنه كل ورقة. ويبدو `clean` عندئذ
هكذا:

| _norm_key | name     | value_a | value_b | completeness_pct | quality_flag   |
|-----------|----------|---------|---------|------------------|----------------|
| objecta   | Object A | 12.4    | 0.87    | 100.0            | Confirmed      |
| objectb   | Object B | 9.1     |         | 50.0             | Needs Review   |
| objectc   | Object C |         |         | 0.0              | Low Confidence |

يحذف `Plotly3DSink` الصفوف التي تفتقد أي قيمة محور، ولا يكتب شيئًا إن لم يبقَ أي صف،
ويستبدل ملف HTML ذرّيًا. ويحتاج إلى الإضافة `viz` عند إنشائه؛ أما استيراد
`sci_etl_core.processors.sinks` فلا يحتاج إلا إلى الإضافة `processors`. والمصارف
متزامنة، فاستدعِ `write` عبر `asyncio.to_thread` من الشيفرة غير المتزامنة.

### تنسيق الرسم {#styling-the-plot}

يتحكم `ScatterPlotConfig` أيضًا في نص التلميح والألوان:

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

- تصبح **`hover_data_columns`** هي `%{customdata[0]}` و`%{customdata[1]}` وهكذا في
  `hover_template`، بترتيب سردها؛ واسم التلميح هو `%{hovertext}`.
- تثبّت **`color_continuous_scale`** و**`color_range`** ألوان عمود لون رقمي، فيكون
  للقيمة اللون نفسه في كل تصدير. ويعنون `color_label` شريط الألوان، أو وسيلة الإيضاح
  لعمود لون فئوي.
- يحدّث **`marker`** علامات كل مسار، ويُطبَّق **`layout`** على تخطيط الشكل في النهاية،
  فيتجاوز `template` والهوامش الافتراضية.

## لبنات بناء أخرى {#other-building-blocks}

- يشغّل **`ClusteringStep(feature_extractor)`** خوارزمية DBSCAN على الخصائص التي يُعيدها
  `FeatureExtractor` الخاص بك.
- يحصر **`ValueClipStep(bounds)`** الأعمدة الرقمية في نطاقات، مثل
  `{"fraction": (0.0, 1.0)}`، محوّلًا القيم غير العددية إلى خلايا فارغة. والحصر يخفي
  القيمة الخارجة عن النطاق خلف قيمة معقولة، فالأفضل رفض هذه القيم بمدقّق أثناء
  الاستخراج.
- يهيّئ **`TableLayoutStep(sort_by, leading_columns, hidden_prefixes)`** جدولًا للنشر:
  يرتّب الصفوف حسب أزواج `(column, ascending)` مع وضع القيم المفقودة في الآخر، ويحذف
  الأعمدة المساعدة مثل `_norm_key` حسب البادئة، وينقل `leading_columns` إلى المقدمة.
- **مدقّقات السجلات** تفحص قواميس الكيانات المفردة: `NumericRangeValidator`
  و`KeywordExclusionValidator` و`CompositeValidator`. تُعيد `validate(entity)` كائن
  `ValidationResult` تسمّي `violations` فيه الحقل والقاعدة اللذين خرقهما كل رفض؛ ويجمع
  `CompositeValidator` مخالفات كل مدقّق يحويه. مرّر واحدًا إلى
  `AsyncLLMEntityExtractor(validator=...)` لحذف الكيانات غير الصالحة قبل التصدير. ويُسجَّل
  كل رفض مع أسبابه، موسومًا بقيمة `label_field` حين تسمّي واحدًا، ويُخزَّن للمراجعة حين
  تمرر مخزن رفض بوصفه `rejections=`:

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

  يرث المدقّق الخاص بك من `RecordValidator` وينفّذ `is_valid`؛ وأعِد تعريف `validate`
  أيضًا للإبلاغ عن أسباب غير "rejected".
- يكتب **`SqlTableSink(url, table_name)`** إطار DataFrame في قاعدة بيانات عبر عنوان
  SQLAlchemy متزامن، في معاملة واحدة، مثل
  `SqlTableSink("sqlite:///results.db", "entities").write(clean)`. ويحتاج إلى الإضافة
  `sql` عند إنشائه. ومثل `Plotly3DSink` يأخذ DataFrame، فاستخدمه بعد المعالجة اللاحقة لا
  بوصفه مصدِّر خط المعالجة.
