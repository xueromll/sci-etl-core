# المساهمة في sci-etl-core

شكرًا لاهتمامك بتحسين `sci-etl-core`! نرحّب ترحيبًا صادقًا بالمستخرِجات والمحلِّلات
والمصدِّرات والواجهات الخلفية للتضمينات الجديدة وبتصحيحات التوثيق، بما في ذلك مساهمات من
يساهمون للمرة الأولى. يساعدك هذا الدليل على البدء بسرعة.

بمشاركتك فإنك توافق على الالتزام بـ [مدونة السلوك](code-of-conduct.md) الخاصة بنا.

## إعداد بيئة التطوير {#development-setup}

```bash
git clone https://github.com/xueromll/sci-etl-core.git
cd sci-etl-core

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[full,dev]"
```

- **يلزم Python 3.11 أو أحدث**؛ إذ تستخدم قاعدة الشيفرة الاتحادات `X | Y` وأصناف البيانات
  ذات `slots=True` و`kw_only=True`.
- **لماذا `[full]`:** تختبر مجموعة الاختبارات كل مكوّن مضمَّن.
- **غير لازم للاختبارات:** `sentence-transformers` ومشغّل SQL حقيقي، فهما يُحاكيان أو
  يُستبدلان ببدائل.

## كيف تعمل قاعدة الشيفرة: اقرأ هذا أولًا {#how-the-codebase-works-read-this-first}

- **التنفيذ غير المتزامن هو الوحيد.** كل مكوّن `async`. لا تُضف نسخًا متزامنة توأمًا
  للمكوّنات؛ فلا يوجد مولّد شيفرة. وتصل التطبيقات المتزامنة إلى خط المعالجة عبر المحوّلات في
  `_adapters.py`.
- **نقطة دخول متزامنة واحدة.** يشغّل `ETLPipeline` (`pipeline.py`) خط المعالجة
  `AsyncETLPipeline` عبر `_sync_bridge.run_sync`. ناقش أي واجهة برمجية متزامنة جديدة في
  مشكلة أولًا.
- **أبقِ حلقة الأحداث حرة.** شغّل الأعمال كثيفة المعالجة أو المتزامنة بـ `asyncio.to_thread`.
  وتتبع المحلِّلات وpandas و`sqlite3` وعمليات إدخال الملفات وإخراجها هذا النمط.
- **احقن المكوّنات المتعاونة.** العملاء والمحلِّلات و`sleep` و`logger` وسائط للمُنشئ كي
  تستطيع الاختبارات استبدالها. اقبل `logger: Callable[[str], None] | None` و`sleep` قابلًا
  للحقن حيثما وُجد توقيت أو إعادة محاولة.
- **لا تبتلع الإلغاء أبدًا.** قبل التقاط الاستثناءات العامة، التقط `asyncio.CancelledError`
  وأعد رفعه (راجع `llm/relevance_async.py`).
- **أشِر إلى الإخفاقات بالاستثناءات.** استخدم التسلسل الموجود في `exceptions.py`. لا تُعِد
  `None` أو نتيجة فارغة عند عطل في النقل، فخط المعالجة يعتمد على `UpstreamError`
  و`MalformedResponseError` للتمييز بين الأعطال ونهاية البيانات.
- **كن آمنًا مع التزامن.** يستدعي خط المعالجة مرشحات الصلة ومستخرِجات الكيانات و`write`
  الخاصة بالمصدِّر و`mark_processed` في وقت واحد. سلسِل الكتابات المشتركة بـ `asyncio.Lock`،
  واكتب الملفات بـ `_atomic_io.atomic_write_text`. و`AsyncCsvExporter`
  و`AsyncFileStateManager` نموذجان جيدان.
- **سجّل عبر مسجِّل الوحدة.** تسجّل كل وحدة بـ `_logger = logging.getLogger(__name__)`،
  بالمستوى `WARNING` لكل ما يغيّر ناتج التشغيل أو كلفته، و`ERROR` لعطل مَصرِف أو مخزن يُبلغ عنه
  التشغيل، و`INFO` للملاحظات الروتينية. لا تضبط المعالجات أو المستويات أبدًا؛ فتلك مهمة
  التطبيق.
- **أبقِ الاستيرادات الاختيارية كسولة.** يربط ملف `__init__.py` في كل حزمة الأسماء العامة
  بوحداتها في `_EXPORTS` ويحمّلها عند أول وصول، فلا يتطلب استيراد مكوّن واحد أبدًا الاعتماديات
  الاختيارية لمكوّن آخر. سجّل الأسماء العامة الجديدة هناك وفي استيرادات `TYPE_CHECKING`
  المقابلة (يتحقق اختبار من اتفاقهما)، وأضف أي اعتمادية جديدة من طرف ثالث إلى إضافة في
  `pyproject.toml`.
- **لا ثوابت خاصة بمجال بعينه** في النواة؛ أبقِها مستقلة عن المجال.

## تشغيل الاختبارات {#running-tests}

تعمل مجموعة الاختبارات دون اتصال، فلا تحتاج إلى شبكة ولا إلى نموذج لغوي حي ولا إلى خدمة
تضمينات.

```bash
pytest                                                # كل شيء دون اتصال
pytest tests/async                                    # المكوّنات غير المتزامنة
pytest tests/contract                                 # مطابقة الأصناف المجردة
pytest --cov=sci_etl_core --cov-report=term-missing   # تقرير التغطية
```

- **تبقى التغطية 100%.** يفشل `pytest --cov=sci_etl_core` إذا قلّت التغطية عن 100% (وهو
  مضبوط في `pyproject.toml`)، فتحتاج الشيفرة الجديدة والمعدّلة إلى اختبارات تغطيها. ولا
  تستخدم `# pragma: no cover` إلا للأسطر التي لا يمكن تشغيلها على منصة الاختبار، مثل
  الاستيرادات الخاصة بنظام تشغيل بعينه. ويقيس التكامل المستمر أيضًا تغطية الفروع ويُبلغ عنها في
  ملخص المهمة؛ لكنها ليست شرطًا بعد.
- **الاختبارات غير المتزامنة** تستخدم العلامة الصريحة `@pytest.mark.asyncio` (الوضع التلقائي
  غير مضبوط)، مع `AsyncMock` أو التثبيتة `mocker`.
- **لا شبكة حقيقية ولا انتظار للتراجع.** حاكِ عملاء HTTP والنموذج اللغوي والتضمينات، واحقن
  `sleep=AsyncMock()` لتخطي فترات التراجع.
- **اختبارات العقود.** لكل تطبيق لصنف مجرد عام حالة في
  `tests/contract/test_abc_conformance.py`؛ أضف حالة لكل تطبيق جديد.
- **اختبارات الخصائص.** ضع الثوابت، ولا سيما تلك التي يجب أن تتشاركها واجهتان خلفيتان مثل
  مخزنَي التضمينات في الذاكرة وفي SQLite، في اختبارات Hypothesis في
  `tests/test_properties.py`.
- **لقطة الواجهة العامة.** يسجّل `tests/api/public_surface.txt` توقيع كل صنف وحقل ودالة
  وطريقة مستقرة، ويفشل `tests/api/test_public_surface.py` حين لا تعود الشيفرة مطابقة له. وحين
  تغيّر الواجهة البرمجية العامة عن قصد، أعد توليد اللقطة، وأودِع الفرق، وأضف إدخالًا له في
  CHANGELOG.md:

  ```bash
  python tests/api/update_surface.py
  ```

  يسرد `tests/api/surface.py` الأسماء المستقرة. ويجب أن يكون كل اسم يستورده
  [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) أو
  [udg-catalogue](https://github.com/xueromll/udg-catalogue) أو يرث منه ضمنها. ويسرد
  `tests/api/consumer_surface.txt` تلك الأسماء. أعد توليده حين يتغير الإصدار المثبّت لدى
  مستهلك، مع قراءة مشروع الفهرس من فرعه البعيد المجلوب لا من نسخة محلية قد تكون متأخرة:

  ```bash
  git -C ../udg-catalogue fetch origin
  python tests/api/scan_consumers.py sci-etl-cli=../sci-etl-cli udg-catalogue=../udg-catalogue@origin/main
  ```
- **الاختبارات الحية.** يشغّل `tests/live` استعلامًا صغيرًا واحدًا على كل مصدر مضمَّن
  ويتحقق من السجلات والبيانات الوصفية والنص الكامل الذي يُعيده. وهذه الاختبارات غير محددة
  افتراضيًا. ويشغّلها سير العمل Live كل ليلة، ولا يكون فحصًا إلزاميًا أبدًا. شغّلها محليًا بـ
  `pytest -m live tests/live`. ومفاتيح حد المعدل الأعلى اختيارية وتُقرأ من `NCBI_API_KEY`
  و`SEMANTIC_SCHOLAR_API_KEY` و`OPENALEX_MAILTO`. ودون مفتاحه، يُتخطى المصدر الذي يظل يجيب
  بـ `429` بدلًا من عدّه فاشلًا.
- **اختبار أداء الإنتاجية.** يمرر `python benchmarks/run_throughput.py` كل مصدِّر مضمَّن لخط
  المعالجة عبر `AsyncETLPipeline` على 1,000 و10,000 و50,000 سجل، ويكتب الأزمنة في
  `benchmarks/results/<version>.json`. ويُعدّ المصدِّر خطيًا حين لا يتجاوز زمنه لكل سجل عند
  أكبر حجم 1.5 ضعف زمنه عند أصغر حجم. وتضيّق `--sizes` و`--repeats` و`--exporters` نطاق
  التشغيل.
- **اختبارات المستهلكين.** يشغّل سير العمل Downstream مجموعتَي اختبارات
  [sci-etl-cli](https://github.com/xueromll/sci-etl-cli) و
  [udg-catalogue](https://github.com/xueromll/udg-catalogue) على كل دفع وطلب سحب، مع تثبيت
  هذه النسخة بدلًا من الإصدار الذي يثبّته كل مشروع، ويفشل عند أي `DeprecationWarning`. وتثبّت
  كل مهمة الإضافات التي يذكرها متطلب المشروع نفسه. لتشغيل مجموعة اختبارات أداة سطر الأوامر
  محليًا:

  ```bash
  git clone https://github.com/xueromll/sci-etl-cli.git ../sci-etl-cli
  pip install -e ".[config,async,arxiv,html,llm,pdf]"
  pip install --no-deps -e ../sci-etl-cli
  pip install click rich pytest pytest-asyncio pytest-mock pytest-cov
  cd ../sci-etl-cli && python -m pytest -W error::DeprecationWarning
  ```

  ومجموعة اختبارات udg-catalogue، التي تثبّت أيضًا نسخة PyTorch الخاصة بالمعالج المركزي:

  ```bash
  git clone https://github.com/xueromll/udg-catalogue.git ../udg-catalogue
  export PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
  pip install -e ".[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]" \
      -r ../udg-catalogue/requirements/app.txt -r ../udg-catalogue/requirements/dev.txt
  cd ../udg-catalogue && python -m pytest -W error::DeprecationWarning
  ```

## أسلوب الشيفرة {#code-style}

- التسمية وفق **PEP 8**: الدوال والمتغيرات بـ `snake_case`، والأصناف بـ `CapWords`،
  والثوابت بـ `UPPER_CASE`.
- **تلميحات الأنواع في كل توقيع عام.** تأتي الحزمة مع `py.typed`؛ فأبقِ التلميحات دقيقة.
- **دوال صغيرة ذات مسؤولية واحدة.** فضّل التركيب وحقن الاعتماديات على التفرع وفق منطق
  مكتوب بشكل ثابت.
- **سلاسل التوثيق للعقود والمقاصد.** وثّق `Raises:` والقرارات غير البديهية؛ ولا تكتب تعليقات
  تكرر ما تقوله الشيفرة.
- **الإنجليزية الأمريكية** للمعرّفات وسلاسل التوثيق.

يعمل ruff وmypy في التكامل المستمر عند كل دفع وطلب سحب، ويُضبطان في `pyproject.toml`. يفحص
ruff مجموعات القواعد `ASYNC` و`UP` و`RUF` و`PT` إلى جانب قواعد pycodestyle وPyflakes وisort
وbugbear. ويفحص mypy العقود الأساسية (`models` و`exceptions` و`observability`
و`pipeline_async` وكل وحدة `async_base`) بخيارات أكثر صرامة: لا تعريفات غير منمّطة، ولا أنواع
عامة مجردة، ولا إعادة لـ `Any`، ولا إعادة تصدير ضمنية. شغّل الاثنين قبل فتح طلب سحب:

```bash
pip install -e ".[full,dev,lint]"
ruff check .
mypy
```

يرتّب `ruff check --fix .` الاستيرادات ويطبّق الإصلاحات الآمنة الأخرى. ولا يُفرض التنسيق، لذا
أبقِ إعادة التنسيق غير المتعلقة بعملك خارج طلب السحب. وسجّل التغييرات التي تخص المستخدمين تحت
الإصدار غير المنشور في [CHANGELOG.md](changelog.md).

## التوثيق {#documentation}

يُبنى موقع التوثيق بـ [MkDocs](https://www.mkdocs.org/) و
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) من `mkdocs.yml` ومجلد
`docs/`، ويُنشر على GitHub Pages.

```bash
pip install -e ".[docs]"
git clone https://github.com/xueromll/sci-etl-cli.git ../sci-etl-cli
pip install --no-deps -e ../sci-etl-cli
mkdocs serve                                          # معاينة على http://127.0.0.1:8000
mkdocs build --strict                                 # الفحص الذي يشغّله التكامل المستمر
```

- **أين توجد الصفحات.** الأدلة ملفات Markdown تحت `docs/`، مدرجة في `nav` الخاص بـ
  `mkdocs.yml`. ويبقى `CHANGELOG.md` و`MIGRATION.md` و`ROADMAP.md` وهذا الدليل و`SECURITY.md`
  و`CODE_OF_CONDUCT.md` في جذر المستودع؛ وتعرضها الصفحات الموجودة تحت `docs/project/`، وتُعاد
  كتابة الروابط بينها لتناسب الموقع.
- **الترجمات.** تقع النسخ الروسية والإسبانية والصينية المبسّطة والعربية من الصفحة بجوارها
  باسم `page.ru.md` و`page.es.md` و`page.zh.md` و`page.ar.md`، وتبني الإضافة
  mkdocs-static-i18n كل لغة تحت مسارها الخاص، مثل `/ru/`. وطلب السحب الذي يغيّر صفحة إنجليزية
  يحدّث ترجماتها الأربع أيضًا. ويسمّي [TRANSLATING.md](translating.md) مالك كل لغة، ويضم
  مسرد المصطلحات والقواعد التي تتبعها الصفحة المترجمة.
- **قسم أداة سطر الأوامر** يأتي من مجلد `docs/` و`nav` في مستودع sci-etl-cli. ويبحث البناء عن
  نسخة بجوار هذه النسخة، أو في المسار المحدد في `SCI_ETL_CLI_DIR`؛ ودونها يُسقط القسم، وهو ما
  يُبلغ عنه `--strict` بوصفه فشلًا. غيّر صفحات أداة سطر الأوامر في ذلك المستودع.
- **مرجع الواجهة البرمجية.** تُولَّد الصفحات الموجودة تحت `docs/reference/` من سلاسل
  التوثيق. ويحتاج أي وحدة عامة جديدة إلى إدخال `::: module.path` في إحداها؛ ويفشل
  `tests/test_docs.py` حتى يوجد ذلك الإدخال.
- **أمثلة الشيفرة.** يتحقق `tests/test_docs.py` أيضًا من أن كل مثال بايثون تحت `docs/` قابل
  للترجمة، ومن وجود كل اسم يستورده من `sci_etl_core`، فإعادة تسمية اسم عام تعني تحديث الأمثلة
  أيضًا.
- **النشر.** ينشر سير عمل التوثيق `master` بوصفه الإصدار `dev`، وكل وسم `v*` بوصفه إصداره
  الفرعي، مثل `0.3`، مع الاسم المستعار `latest`. ويستخدم البناء المعتمد على الوسم صفحات أداة
  سطر الأوامر من أحدث إصدار لـ sci-etl-cli، أو من فرعه الافتراضي حين لا يحوي ذلك الإصدار
  `mkdocs.yml`. ولا يلزم نشر أي شيء يدويًا.

## إصدار النسخ {#releasing}

- **إصدارات التطوير.** مباشرة بعد أي إصدار ينتقل `master` إلى إصدار التطوير التالي، مثل
  `0.7.0.dev0` بعد `0.6.0`، كي لا يدّعي بناء من `master` أبدًا أنه إصدار رسمي.
- **شرط الإصدار.** يؤدي دفع وسم `v*` إلى تشغيل مجموعة اختبارات التكامل المستمر وسير العمل
  Downstream على الإيداع الموسوم. ولا يُبنى التوزيع ويُنشر إلا حين ينجح الاثنان، فلا يُنشر أبدًا
  إصدار يكسر sci-etl-cli أو udg-catalogue. ويجب أن يطابق الوسم الإصدار في `pyproject.toml`.
- **الإهمالات.** منذ 0.6.0 يظل الاسم المهمل يعمل لإصدارين فرعيين على الأقل قبل إزالته.
- **قبل الوسم.** أرّخ القسم غير المنشور في `CHANGELOG.md`، وحدّث الإصدارات المدعومة في
  `SECURITY.md`، وأعد تشغيل `python benchmarks/run_throughput.py` ليضم `benchmarks/results/`
  الإصدار الجديد.
- **الإجراءات المثبّتة.** تثبّت مسارات العمل كل إجراء (action) على قيمة SHA لإيداع، مع الوسم في
  تعليق في آخر السطر مثل `# v5`. وللانتقال إلى إصدار أحدث، احصل على قيمة SHA الخاصة به بـ
  `git ls-remote https://github.com/actions/checkout refs/tags/v5` وحدّث التثبيت والتعليق معًا.

## صيغة الإيداعات {#commit-format}

استخدم [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>
```

الأنواع الشائعة: `feat` و`fix` و`docs` و`test` و`refactor` و`perf` و`chore`. علّم التغييرات
الكاسرة بـ `!` (مثل `refactor(core)!: ...`).

أمثلة:

```
feat(extractors): add PubMed async extractor
fix(exporters): serialize concurrent CSV upserts
docs(readme): document ETLPipeline event-loop behavior
```

اجعل الملخص بصيغة الأمر وأقصر من 72 محرفًا تقريبًا. وأشر إلى المشكلات في متن الرسالة
(`Closes #123`).

## عملية طلب السحب {#pull-request-process}

1. **افتح مشكلة أولًا** لأي أمر غير بسيط، كي نتفق على النهج.
2. **أنشئ فرعًا** من `master`، مثل `feat/pubmed-extractor`.
3. **اكتب اختبارات** مع تغييرك؛ وأبقِ التغطية 100%.
4. **شغّل** مجموعة الاختبارات محليًا (إضافة إلى فحص الشيفرة وفحص الأنواع إن كنت تستخدمهما).
5. **حدّث التوثيق** للتغييرات التي تخص المستخدمين:
   - الصفحات تحت `docs/` لطريقة الاستخدام؛ وأبقِ `README.md` نظرة عامة قصيرة
   - الترجمات الروسية والإسبانية والصينية والعربية لكل صفحة إنجليزية تغيّرها، وفق
     [TRANSLATING.md](translating.md)؛ وإن تعذّرت عليك كتابة إحداها فاذكر ذلك، ويضيفها مالك
     تلك اللغة قبل الدمج
   - `MIGRATION.md` للتغيير الكاسر، تحت الإصدار الذي يتضمنه
   - `docs/guide/migrating-a-pipeline.md` حين يؤثر التغيير في نقل خط معالجة قائم إلى المكتبة
   - `ROADMAP.md` حين تُصدر بندًا مدرجًا
   - وصف طلب السحب لأي تغيير كاسر، مع ما يلزم المستخدمين تحديثه
6. **املأ** [قالب طلب السحب](https://github.com/xueromll/sci-etl-core/blob/master/.github/PULL_REQUEST_TEMPLATE.md).
7. **أبقِ طلبات السحب مركّزة**: تغيير منطقي واحد لكل طلب سحب هو الأسهل مراجعة.

سيراجع أحد القائمين على الصيانة طلبك سريعًا. توقّع نقاشًا وديًا وبنّاءً؛ فالتغييرات المطلوبة
تخص الشيفرة، لا تخصك أنت أبدًا.

## إضافة مكوّن جديد {#adding-a-new-component}

تتصل معظم المساهمات بصنف أساسي مجرد قائم:

| المكوّن | ارث من | نفّذ | العقد |
|---------|--------|------|-------|
| المستخرِج | `AsyncExtractor` | `async fetch_page(query, cursor, page_size) -> ListingPage`، `async fetch_full_text`؛ و`cursor_for_offset` حين تكون المؤشرات إزاحات عشرية | أعِد كل مدخل تستطيع قراءته: فخط المعالجة يتخطى المعرّفات المعالَجة. احتسب المدخلات التي لا معرّف لها في `entries`، وأعِد `next_cursor=None` في الصفحة الأخيرة، و`truncated=True` في الصفحة التي تبلغ حد نتائج المصدر الخاص. ارفع `UpstreamError` حين يتعذّر الوصول إلى المصدر بعد إعادات المحاولة، و`ExtractionError` حين يرفض طلبًا صراحة، و`MalformedResponseError` لقائمة غير قابلة للقراءة، و`StaleCursorError` لمؤشر لم يعد المصدر يقبله. |
| المحلِّل | `Parser` (واختياريًا `TableParser`) | `extract_text(content: bytes) -> str` | متزامن؛ يشغّله المستدعي في خيط عامل. ارفع `ParsingError` للبايتات التي يتعذّر عليه قراءتها. |
| عميل النموذج اللغوي | `AsyncLLMClient` | `async complete_json(system_prompt, user_content, timeout)`؛ واختياريًا `complete_structured(..., schema, timeout)` و`invalidate(..., schema=None)` | أعِد كائن JSON المحلَّل؛ وارفع `LLMError` عند الفشل أو حين لا يكون المتن كائن JSON. أعِد تعريف `complete_structured` حين يدعم المزوّد مخرجات JSON Schema؛ والتنفيذ الافتراضي يستدعي `complete_json`. |
| ذاكرة التخزين المؤقت لاستجابات النموذج اللغوي | `AsyncLLMResponseCache` | `async get(key)`، `async set(key, response)`، `async clear()` | تُعيد `get` القيمة `None` لمفتاح مفقود. أعِد نسخًا، كي لا يستطيع مستدعٍ يغيّر استجابة أن يغيّر الذاكرة المؤقتة. ارفع `LLMCacheError` لعطل في التخزين؛ فيسجّله `CachingLLMClient` ويستدعي النموذج اللغوي بدلًا من ذلك. أضف `aclose()` إن كنت تحتفظ باتصالات. |
| مرشح الصلة | `AsyncRelevanceFilter` | `async is_relevant(record)` | أعد رفع `CancelledError`. |
| مستخرِج الكيانات | `AsyncEntityExtractor[E]` | `async extract(text) -> Sequence[E]`؛ و`extract_record(record, text)` حين يلزم السجل | يستدعي خط المعالجة `extract_record`، التي يستدعي تنفيذها الافتراضي `extract`. ارفع استثناءً عند الفشل بدلًا من إعادة `[]`، ليُعاد السجل. والمستخرِج الذي يحتاج إلى السجل يضبط `requires_record = True`؛ والمغلّف يفوّض إلى `extract_record` الداخلية. |
| المصدِّر | `AsyncExporter[E]` | `async write(record, entities)`؛ واختياريًا `open` و`flush` و`aclose` و`durable_writes` | خذ الوجهة في المُنشئ. تعمل `write` لكل سجل معالَج، بما فيه السجل الذي لا كيانات له، وربما في وقت واحد، ويجب أن تكون متساوية القوة. ومع `durable_writes = False` يجب أن تجعل `flush` كل كتابة سابقة دائمة. |
| مدير الحالة | `AsyncStateManager` | `load_processed_ids`، `mark_processed`، `load_metadata`، `save_metadata` | آمن مع التزامن. أعِد تعريف `record_failure` و`failure_counts` لدعم الحجر؛ فالتنفيذات الافتراضية لا تتتبّع شيئًا. سجّل إصدار المخطط وارفض ملفًا من إصدار أحدث. أعِد تعريف `flush()` إن كنت تخزّن مؤقتًا؛ وأضف `aclose()` إن كنت تحتفظ باتصالات. |
| مولّد التضمينات | `AsyncEmbedder` | `async embed(texts) -> list[list[float]]` | متجه واحد لكل مدخل، بالترتيب نفسه؛ وارفع `EmbeddingError`. |
| المخزن المتجهي | `AsyncEmbeddingStore` | `add`، `delete_record`، `query`، `count` | استبدل المقاطع التي لها `(record_id, chunk_index)` نفسه؛ وتحذف `delete_record` كل مقاطع السجل. أعِد تعريف `replace_record` (الحذف ثم الإضافة افتراضيًا) إن كانت واجهتك الخلفية قادرة على الأمرين ذرّيًا. لا تُعِد أبدًا نتائج بدرجات غير منتهية. طابِق سلوك `InMemoryEmbeddingStore` في `top_k` و`min_score` و`exclude_record_id`. سلسِل استخدام الاتصال المشترك، وارفع `EmbeddingStoreError`. نفّذ `iter_records` (المقاطع بترتيب `chunk_index`، والسجلات بترتيب `record_id`، دون متجهات) إن كان ينبغي أن يُملأ الفهرس النصي من مخزنك. |
| المقطِّع | `TextChunker` | `chunk(text) -> list[str]` | مقاطع مرتبة تغطي النص. |
| مخزن البحث النصي | `AsyncTextSearchStore` | الخاصية `facet_keys`، و`index`، و`delete_record`، و`search`، و`filter_ids`، و`get_documents`، و`facet_counts`، و`count` | خذ استعلامات محلَّلة، لا نصًا أبدًا. ارفض بـ `require_rankable` الاستعلام الذي لا تستطيع `search` ترتيبه. رتّب الدرجات المتساوية حسب `record_id`، وطبّق المرشحات قبل `limit`. ارفع `ValueError` قبل أي إدخال وإخراج لمفتاح مرشح أو وجه خارج `facet_keys` أو لمرشحين على مفتاح واحد (`validate_filters`، `validate_facet_keys`). اقبل `MetadataFilter` و`RangeFilter`، وقارن النطاقات بـ `tag_in_range`، واملأ `TextHit.snippets` لكل حقل فيه مطابقة مُبرزة. أعِد تعريف `range_counts` (استدعاء `filter_ids` مرة لكل نطاق افتراضيًا) إن كنت تستطيع العد في قراءة واحدة. طابِق نتائج `InMemoryTextSearchStore`، وارفع `SearchStoreError`. |
| مصدر الحواف | `AsyncEdgeSource` | الخاصية `kind`، و`async neighbours(record_ids, limit)` | اربط كل معرّف مطلوب، حتى لو لم يكن له جيران، بما يصل إلى `limit` زوجًا من `(record_id, weight)`، الأفضل أولًا، حيث يعني الوزن الأعلى ترابطًا أكبر. لا تُغلق أبدًا المخازن التي أُعطيت لك. |
| المعالِج | `Processor` | `process(frame) -> DataFrame` | لا تعدّل إطار البيانات المُدخل. |
| المدقّق | `RecordValidator` | `is_valid(record) -> bool`؛ واختياريًا `validate(record) -> ValidationResult` | يعمل على قاموس كيان واحد. أعِد تعريف `validate` لتسمية الحقل والقاعدة في كل رفض؛ ويجب أن يرفض بالضبط ما ترفضه `is_valid`. |

سجّل الصنف الجديد في خريطة `_EXPORTS` واستيرادات `TYPE_CHECKING` في حزمته الفرعية. وتحتاج
الوحدة الجديدة أيضًا إلى إدخال في صفحتها تحت `docs/reference/`. وإن كان صنفًا أساسيًا يتعامل معه
المستخدمون، فأضفه بالطريقة نفسها إلى `sci_etl_core/__init__.py`. وأضف حالة له في
`tests/contract/test_abc_conformance.py`.

برمجة ممتعة، وشكرًا لمساهمتك!
