# سجل التغييرات

تُسجَّل هنا كل التغييرات البارزة في sci-etl-core. ويتبع التنسيق
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)، وتتبع الإصدارات
[الإصدار الدلالي](https://semver.org/). وحتى 1.0 قد يغيّر الإصدار الفرعي السلوك؛
ويُسرد كل تغيير من هذا النوع تحت **التغييرات**.


## [0.6.0] - 2026-09-27 {#060-2026-09-27}

يغيّر هذا الإصدار عقد البيانات: يمكن لمستخرِجات الكيانات أن تُعيد كيانات منمّطة، وتتلقى
المصدِّرات كل سجل مع كياناته، وتسجّل المكتبة عبر الوحدة القياسية `logging`، ولا يحتاج التثبيت
الأساسي إلا إلى Pydantic. ويضيف الادعاءات مع أدلتها ومصدرها. راجع "الترقية إلى 0.6" في
MIGRATION.md.

### الإضافات {#added}

- **دورة حياة المصدِّر.** لـ `AsyncExporter` الدوال `open()` و`write(record, entities)`
  و`flush()` و`aclose()`، ويبيّن `durable_writes` ما إذا كانت `write` أو `flush` هي التي تجعل
  الكيانات دائمة. ولا يعلّم خط المعالجة السجل معالَجًا إلا بعد أن تصبح كياناته دائمة، فقد يكرر
  الانهيار سجلًا لكنه لا يُضيعه أبدًا.
- `AsyncCsvExporter`، الذي يكتب صفًا لكل كيان مع `record_id` الخاص بورقته، ويحتفظ بكل مفتاح آخر
  في عمود `extra`، ولا يدمج قيمة ولا يقتطعها ولا يحوّلها أبدًا. ويكتب الملف مرة واحدة في كل تشغيل
  من سجل لا يُضاف إليه إلا في آخره، فيزداد زمن التصدير خطيًا مع عدد السجلات. والخلايا التي قد
  ينفّذها برنامج جداول بيانات بوصفها صيغة تُسبق بفاصلة عليا؛ أما الأعداد البسيطة مثل `-5.361`
  فتُكتب دون تغيير.
- `AsyncJsonlExporter`، الذي يُلحق سطر JSON واحدًا لكل سجل، و`read_jsonl_export`، التي تقرأ آخر
  سطر لكل سجل.
- **كيانات منمّطة.** يتحقق `AsyncLLMEntityExtractor(schema=Model)` من كل كيان مقابل نموذج
  Pydantic ويُعيد نسخًا من النموذج. ويطلب مخرجات منظَّمة وفق JSON Schema عبر
  `AsyncLLMClient.complete_structured` الجديدة، التي يفعّلها
  `AsyncOpenAICompatibleClient(structured_output=True)` و`LLMConfig.structured_output` لنقاط
  النهاية التي تدعمها. وتبني `entity_list_schema` المخطط المطلوب.
- **أسباب الرفض.** تُعيد `RecordValidator.validate` كائن `ValidationResult` مؤلفًا من كائنات
  `Violation` تسمّي الحقل والقاعدة في كل رفض. وتُبلغ المدقّقات المضمّنة عن قواعدها، وتجمع
  `CompositeValidator.validate` مخالفات كل مدقّق. ويُسجَّل الرفض مع أسبابه.
- `AsyncEntityExtractor.extract_record(record, text)` و`requires_record`، للمستخرِجات التي
  تحتاج إلى السجل. ويستدعي خط المعالجة `extract_record`.
- تُعيد `AsyncLLMEntityExtractor.prepare` النص المرسل إلى النموذج، ويصف `stamp` النموذج
  والموجِّه والمخطط وإصدار المكتبة وراء كياناته. ويحتفظ `rejections=` بالكيانات المرفوضة في مخزن
  رفض.
- `response_cache_key(schema=, variant=)` و`CachingLLMClient(variant=)`. ويدخل مخطط الطلب
  المنمّط في مفتاح الذاكرة المؤقتة.
- `sci_etl_core.claims` (مؤقتة): `Claim` و`ClaimDraft` و`EvidenceSpan` و`ExtractionStamp`
  و`locate_quote` و`AsyncLLMClaimExtractor`، ومخزنا الادعاءات `InMemoryClaimStore`
  و`AsyncSqliteClaimStore`، و`AsyncClaimStoreExporter`، ومخزنا الرفض `InMemoryRejectionStore`
  و`AsyncSqliteRejectionStore`.
- يضيف `DeduplicationStep(source_column=)` عمود `sources` يسرد المصادر المتمايزة، مثل
  `record_id` لكل ورقة، لكل الصفوف المدموجة في كل صف من المخرجات.
- `ExportError` و`ClaimError` و`ClaimStoreError`.
- الإضافات `config` و`arxiv` و`xml` و`html` و`processors`.
- `load_config(load_env=True)` و`load_config_async(load_env=True)`.

### التغييرات {#changed}

- **تغيير كاسر:** تأخذ المصدِّرات وجهتها عند إنشائها، وتنفّذ `write(record, entities)` بدلًا
  من `export(data, destination)`. ولم يعد خط المعالجة يأخذ `destination`.
- **تغيير كاسر:** يكتب خط المعالجة كل سجل معالَج إلى المصدِّر، بما فيه السجل الذي لا كيانات له،
  كي يستطيع المصدِّر مسح الصفوف التي لم تعد إعادة الاستخراج تجدها.
- **تغيير كاسر:** يفتح خط المعالجة المصدِّر قبل أول طلب للقائمة، ويفرّغه بعد كل صفحة، ويفرّغه
  ويُغلقه قبل حفظ الحالة أيًّا كانت طريقة انتهاء التشغيل. وعطل `open` يُجهض التشغيل؛ وعطل
  `flush` يترك سجلات الصفحة دون تسوية دون احتساب محاولة عليها.
- **تغيير كاسر:** لا يتطلب التثبيت الأساسي إلا `pydantic`. ثبّت الإضافة `config` لـ
  `load_config`، و`arxiv` لـ `AsyncArxivExtractor`، و`xml` لمستخرِج PubMed ومحلِّلَي JATS
  وDOCX، و`html` لـ `HtmlTextParser`، و`processors` لمعالِجات pandas ومصارف الجداول.
- **تغيير كاسر:** لا تقرأ `load_config` و`load_config_async` ملف `.env` إلا حين تُعطيان
  `env_path` أو `load_env=True`.
- **تغيير كاسر:** تسجّل كل وحدة عبر `logging.getLogger(__name__)` تحت المسجِّل `sci_etl_core`،
  بالمستوى `WARNING` للسجلات الفاشلة والمتخطّاة، و`ERROR` لأعطال المصارف والحالة، و`INFO`
  للملاحظات الروتينية. ولا تضبط المكتبة أي معالجات.
- **تغيير كاسر:** `AsyncEntityExtractor` و`AsyncExporter` عامّان في نوع الكيان، وكل وسائط
  `AsyncLLMEntityExtractor` بعد `system_prompt` لا تُمرَّر إلا بأسمائها.
- تأخذ `AsyncLLMClient.invalidate` الوسيط `schema=` للطلب المنمّط.
- لم تعد الإضافة `async` تثبّت `aiofiles`، ولم تعد الإضافة `sql` تثبّت `aiosqlite`.
- يعيد `AsyncArxivExtractor` المحاولة عند الاستجابة `406` بدلًا من إفشال الطلب، لأن arXiv
  يُعيدها على نحو متقطع لطلبات صحيحة.

### المُزالات {#removed}

- الواجهات المتزامنة `Extractor` و`StateManager` و`Exporter` و`LLMClient` و`RelevanceFilter`
  و`EntityExtractor` وأصناف `Sync*Adapter`.
- `LegacyExtractorAdapter`.
- `AsyncExporter.export` والوسيط `destination` في خط المعالجة.
- `AsyncCsvUpsertExporter`؛ استخدم `AsyncCsvExporter`.
- `AsyncSqlTableExporter` و`AsyncPlotly3DExporter`؛ استخدم `SqlTableSink` و`Plotly3DSink`.
  ويُستورد `ScatterPlotConfig` من `sci_etl_core.processors`.
- كل وسائط `logger=`، و`configure_logging`، و`AsyncETLPipeline.log`.

## [0.5.1] - 2026-09-26 {#051-2026-09-26}

يمنع هذا الإصدار استجابات النموذج اللغوي التي لا تحمل إجابة من تسوية السجل، ويمنع الذاكرة
المؤقتة للنموذج اللغوي من إعادتها، ويضيف حدودًا لحجم التنزيل وفك الضغط. ويُخفق أول تشغيل بعد
الترقية في الذاكرة المؤقتة للنموذج اللغوي مرة واحدة. راجع "الترقية إلى 0.5.1" في MIGRATION.md.

### الإضافات {#added_1}

- تُبلغ `AsyncLLMClient.invalidate(system_prompt, user_content)` عن استجابة مرفوضة، وتُزيل
  `AsyncLLMResponseCache.delete(key)` إدخالًا واحدًا؛ وتنفّذها كلتا الذاكرتين المؤقتتين
  المضمّنتين.
- **حدود الحجم.** يحدّ `max_download_bytes` في `AsyncArxivExtractor` و`AsyncOpenAlexExtractor`
  و`AsyncPubMedExtractor` و`AsyncSemanticScholarExtractor` كل متن استجابة بعد فك ترميزه، ويحدّ
  `LatexTarballParser(max_tex_bytes=)` حجم TeX المفكوك من نسخة e-print واحدة. وصفحة القائمة
  الكبيرة جدًا ترفع `ExtractionError`؛ أما تنزيل النص الكامل أو نسخة e-print الكبيرة جدًا
  فيُسجَّل ويُتجاوز. وكلاهما غير محدود افتراضيًا.
- تبني `AsyncArxivExtractor.from_config(full_text=)` محدِّد المعدل الخاص بالمستخرِج من قسم
  الإعداد `full_text`.
- يوفّر `AsyncOpenAICompatibleClient` و`CachingLLMClient` القيمتين `base_url` و`temperature`،
  ويوفّر كل `AsyncLLMClient` القيمة `response_format`، وافتراضيها `{"type": "json_object"}`.
  وتقبل `response_cache_key` الثلاث جميعها بوصفها وسائط مسمّاة.

### التغييرات {#changed_1}

- صار الإكمال الفارغ من النموذج اللغوي يُفشل السجل بدلًا من تسويته. فترفع
  `AsyncOpenAICompatibleClient.complete_json` الاستثناء `LLMError` حيث كانت تُعيد `{}`، فيعيد خط
  المعالجة السجل في التشغيل التالي بدلًا من تعليمه معالَجًا دون تصدير أي شيء.
- ترفع `AsyncLLMEntityExtractor.extract` الاستثناء `LLMError` حين لا تحوي الاستجابة قائمة
  كيانات: أي حين تكون فارغة، أو فيها عدة مفاتيح ليس أيٌّ منها `result_key`. وكانت تُعيد `[]`،
  فيُعلَّم السجل معالَجًا.
- يُغلق `AsyncLLMRelevanceFilter` و`AsyncEmbeddingRelevanceFilter` مع `default_on_error=False`
  عند الخطأ: فالاستدعاء الفاشل أو الحكم غير الواضح يرفع استثناءً، ويُعاد السجل في التشغيل التالي.
  وكان يُقرأ على أنه غير ذي صلة، فيُعلَّم السجل معالَجًا إلى الأبد.
- صار مفتاح الذاكرة المؤقتة للنموذج اللغوي يتضمن `base_url` لنقطة النهاية ودرجة الحرارة وتنسيق
  الاستجابة، فلم تعد الإجابة المخزنة لمزوّد أو درجة حرارة أو تنسيق ما تُقدَّم لغيره. ولا يُعثر على
  الاستجابات التي خزّنتها إصدارات سابقة، فيستدعي أول تشغيل بعد الترقية النموذج اللغوي لكل طلب.
- يظل `AsyncLLMResponseCache` الخاص بطرف ثالث الذي يفتقر إلى `delete` يقدّم الاستجابات التي
  ترفضها المكتبة. نفّذ `delete`، أو اقبل الإعادة.
- تفتح `PdfPlumberParser.extract_text` ملف PDF مرة واحدة لنصه وجداوله، حيث كانت تفتحه مرتين.
- صارت `AsyncSqliteEmbeddingStore.query` أسرع بكثير عند استدعائها مرارًا. إذ يُبقي المخزن
  متجهاته في الذاكرة ولا يعيد قراءتها إلا بعد تغيّر الملف، ويحسب درجاتها بضرب NumPy واحد، ولا
  يقرأ النص والبيانات الوصفية إلا للمقاطع المُعادة. ويُبنى رسم استكشاف بياني على ذاكرة من 9,000
  مقطع أسرع بنحو أربع مرات. وصار المخزن يُبقي متجهاته في الذاكرة بين الاستعلامات حتى يُغلق.
- لم تعد الإصدارات تُعلَّق حتى يعمل sci-etl-cli وudg-catalogue عليها؛ بل يُبلَّغ عن جاهزية
  المستهلكين في ملاحظات الإصدار بدلًا من ذلك.

### الإصلاحات {#fixed}

- يعيد `AsyncArxivExtractor` المحاولة عند انتهاء مهلة الطلب `408`، كما تفعل المستخرِجات المضمّنة
  الأخرى. وصار يتشارك معها شيفرة إعادة المحاولة، فتبدأ رسائل إعادة المحاولة والفشل لديه بـ
  `arXiv` وتسمّي الإجراء، مثل `arXiv LaTeX fetch for '2401.00001v1' failed after 3 attempts`.
- ترفع `AsyncSqliteFts5Store.search` الاستثناء `SearchQueryError` مع ذكر إصدار SQLite حين تعجز
  SQLite عن إبراز مجموعة `NEAR` مقيدة بحقل داخل `OR` أو `NOT`، كما يفعل SQLite 3.50.4 في بعض
  المستندات. وكانت ترفع `SearchStoreError` مع "database disk image is malformed"، مما يوحي بفهرس
  تالف.
- لم يعد `CachingLLMClient` يعيد استجابة رفضها مستخرِج الكيانات أو مرشح الصلة. فقد كانت
  الاستجابة المرفوضة تُخزَّن، فتحصل كل إعادة محاولة على الإجابة نفسها حتى يُحجر السجل، دون سؤال
  النموذج مرة أخرى.

## [0.5.0] - 2026-09-25 {#050-2026-09-25}

يغيّر هذا الإصدار طريقة تنقل المستخرِجات بين صفحات القائمة، وحالة التشغيل المحفوظة، وطريقة إنشاء
خط المعالجة. وتُرقّى الحالة التي حفظها 0.4 تلقائيًا. راجع "الترقية إلى 0.5" في MIGRATION.md
لتغييرات الشيفرة.

### الإضافات {#added_2}

- **التنقل بالمؤشر.** تُعيد المستخرِجات `ListingPage` من `fetch_page`، مع مؤشر الصفحة التالية.
  والمستخرِجات التي تتنقل بالإزاحة تنفّذ أيضًا `OffsetListing`، الذي تتطلبه تشغيلات
  `newest_first` و`run(start_index=)`.
- **حجر للسجلات التي تظل تفشل.** يتخطى `run(max_attempts=3)` السجل الذي فشل في 3 تشغيلات.
  وتعدّ `RunMetrics.quarantined` السجلات المتخطّاة. ويخزّن مديرا الحالة المضمّنان محاولات كل سجل
  وآخر خطأ له.
- **يُبلَّغ عن حدود النتائج.** تُظهر `RunMetrics.listing_truncated` و`PageFetched.truncated`
  و`PipelineMetadata.truncated` متى توقف المصدر عند حد نتائجه. وتتضمن أحداث التقدم أيضًا
  `cursor` الصفحة.
- **مصارف الجداول.** يكتب `SqlTableSink` و`Plotly3DSink` في `sci_etl_core.processors.sinks`
  إطار `DataFrame` بعد المعالجة اللاحقة.
- **إصدارات المخطط.** تسجّل قاعدة بيانات حالة SQLite والذاكرة المؤقتة للنموذج اللغوي ومخزن
  التضمينات وحالة الملفات إصدار المخطط. ويُرفض الملف الذي كتبه إصدار أحدث، مع `StateStoreError`
  لملفات الحالة.
- `StaleCursorError`، للمؤشر الذي لم يعد المصدر يقبله.
- `BaseAppConfig.strict_sections`، لإلغاء التحقق الصارم من الإعداد.
- `LegacyExtractorAdapter`، الذي يشغّل مستخرِجًا كُتب لـ 0.4 إلى أن يُنقل. وهو مهمل أصلًا.

### التغييرات {#changed_2}

- **تغيير كاسر:** تحل `AsyncExtractor.fetch_page(query, cursor, page_size)` محل `search`
  و`parse_listing`. وصار خط المعالجة يتخطى السجلات المعالَجة بنفسه.
- **تغيير كاسر:** يحل `PipelineMetadata.cursor` محل `last_start_index`.
- **تغيير كاسر:** تأخذ مُنشئات خطوط المعالجة المكوّنات المتعاونة الخمسة موضعيًا أو بأسمائها، وكل
  الوسائط الأخرى بالاسم. وتأخذ `run()` كل وسيط بعد `query` بالاسم.
- **تغيير كاسر:** يجب إنشاء `RawRecord` و`PipelineMetadata` و`TokenUsage` و`RunMetrics` وأحداث
  التقدم بوسائط مسمّاة.
- **تغيير كاسر:** المفاتيح المجهولة في أقسام إعداد المكتبة، مثل `search.bm25.titel`، تُفشل
  التحقق بدلًا من أن تُتجاهل.
- **تغيير كاسر:** يلزم Python 3.11 أو أحدث.
- صار التشغيل الذي يبلغ حد نتائج المصدر يكتمل، ويبدأ التشغيل التالي من الصفحة الأولى من جديد
  بدلًا من التوقف عند الحد.
- المؤشر الذي يرفضه المصدر يعيد بدء القائمة من الصفحة الأولى مرة واحدة.
- يتنقل `AsyncOpenAlexExtractor` بمؤشرات OpenAlex ولم يعد مقتصرًا على أول 10,000 نتيجة. ولم يعد
  يدعم `newest_first`.
- يتوقف `AsyncPubMedExtractor` و`AsyncSemanticScholarExtractor` عند آخر صفحة من النتائج دون طلب
  فارغ إضافي.

### الإهمالات {#deprecated}

تظل هذه تعمل في 0.5 وتُزال في 0.6.0.

مع بديل متاح الآن (`DeprecationWarning`):

- الواجهات المتزامنة `Extractor` و`StateManager` و`Exporter` و`LLMClient` و`RelevanceFilter`
  و`EntityExtractor` وأصناف `Sync*Adapter`؛
- `LegacyExtractorAdapter`؛
- `AsyncSqlTableExporter` و`AsyncPlotly3DExporter`، اللذان يستبدلهما `SqlTableSink`
  و`Plotly3DSink`.

مع بديل يصل في 0.6.0 (`PendingDeprecationWarning`، فلا يلزم تغيير شيء بعد):

- وسائط `logger=` و`configure_logging`؛
- `AsyncETLPipeline(destination=)`؛
- `AsyncExporter.export` و`AsyncCsvUpsertExporter`.

### المُزالات {#removed_1}

- مفتاحا الإعداد `pipeline.max_records` و`pipeline.max_workers`، وخاصيتا `PipelineConfig`
  المقابلتان، و`run(max_records=)`. استخدم `total_limit` و`max_concurrency`.
- `build_retrying_session`، و`requests` من الإضافة `full`.

### الإصلاحات {#fixed_1}

- لم يعد `AsyncPubMedExtractor` يطلب نتائج بعد النتيجة رقم 9,999، التي ترفضها PubMed.

## [0.4.1] - 2026-09-25 {#041-2026-09-25}

### التغييرات {#changed_3}

- يستخدم `HttpConfig.user_agent` و`build_async_client` افتراضيًا
  `sci-etl-core/<installed version>` بدلًا من `sci-etl-core/0.1`.

### الإصلاحات {#fixed_2}

- تتحقق `load_config_async` و`AsyncCsvUpsertExporter` من وجود الملف في خيط عامل بدلًا من حجب
  حلقة الأحداث.
- تتطلب الإضافتان `sql` و`full` الحزمة `sqlalchemy[asyncio]`، فتثبّتان `greenlet`. ولم يعد
  SQLAlchemy 2.1 يثبّتها افتراضيًا، ودونها كان يتعذّر استيراد `AsyncSqlTableExporter`.

## [0.4.0] - 2026-09-16 {#040-2026-09-16}

### الإضافات {#added_3}

- `AsyncPubMedExtractor` و`AsyncSemanticScholarExtractor` و`AsyncOpenAlexExtractor`. يملأ كل
  منها `RawRecord.metadata` بالحقلين `authors` و`categories`، وبالحقلين `published` و`year` حين
  يكون للمصدر تاريخ، ويعيد المحاولة عند أعطال النقل و`408` و`429` وأخطاء الخادم، مع مراعاة
  `Retry-After`. ويخزّن `AsyncOpenAlexExtractor` أيضًا الأعمال التي تستشهد بها الورقة تحت
  `references`.
- `DocxParser` لملفات Word بصيغة `.docx`، و`JatsXmlParser` لـ JATS XML، الذي تُعيد
  `parse_article` الخاصة به كائن `JatsArticle` يتضمن الأقسام والمؤلفين والكلمات المفتاحية
  والمعرّفات والمراجع.
- التخزين المؤقت لاستجابات النموذج اللغوي: يغلّف `CachingLLMClient` أي `AsyncLLMClient` ويجيب
  عن الطلبات المتكررة من `AsyncLLMResponseCache`، سواء `InMemoryLLMResponseCache` أو
  `AsyncSqliteLLMResponseCache`. ويُسجَّل عطل الذاكرة المؤقتة ويُحتسب في `CacheStats`، وترفعه
  المخازن بوصفه `LLMCacheError`، ولا يُفشل أبدًا أي طلب إلى النموذج.
- الإيقاف السلس: يأخذ `AsyncETLPipeline(shutdown=)` و`ETLPipeline(shutdown=)` كائن
  `ShutdownSignal`، فيتيح SIGINT أو SIGTERM أو `request()` للسجلات الجارية أن تكتمل ويرفع
  `PipelineInterrupted`، وهو صنف فرعي من `PipelineAborted`. وصار كل تشغيل ينتهي باستدعاء
  `flush()` لمدير الحالة، أيًّا كانت طريقة انتهائه.
- أحداث التقدم ومقاييس التشغيل: تتلقى `on_event` الأحداث `RunStarted` و`PageFetched`
  و`RecordFinished` و`PageFinished` و`RunFinished` من `sci_etl_core.observability`، وتُعيد
  `last_run_metrics` كائن `RunMetrics` مع الأعداد والمدد ونتيجة التشغيل والرموز التي استهلكتها
  `usage_sources`. ويدعم `TokenUsage` العاملين `+` و`-`.
- يلتقط `run(newest_first=True)` الإرسالات الجديدة في قائمة مرتبة من الأحدث دون إعادة المسح من
  الإزاحة 0. ويكتسب `PipelineMetadata` الحقول `head_ids` و`head_offset` و`tail_ids`، التي
  تحفظها الواجهتان الخلفيتان للحالة.
- `rate_limiter` في كل مستخرِج مضمَّن وفي `AsyncOpenAICompatibleClient` و`AsyncOpenAIEmbedder`،
  و`HostRateLimiter` للحدود الخاصة بكل مضيف.
- مكوّنات مبنية من الإعداد: `AsyncArxivExtractor.from_config`
  و`AsyncOpenAICompatibleClient.from_config` و`AsyncETLPipeline.from_config`
  و`ETLPipeline.from_config`، إضافة إلى `HttpConfig.build_client()`
  و`RateLimitConfig.build_limiter()` و`PipelineConfig.run_arguments()`. ويبني قسم الإعداد
  `search` الكائنات `BM25Weights` و`FusionParams` و`HybridParams` و`GraphParams`. ويكتسب
  `PipelineConfig` الحقل `newest_first`، و`AsyncOpenAICompatibleClient` الخاصية `model`.
- يحذف `AsyncLLMEntityExtractor(validator=, logger=, label_field=)` الكيانات التي يرفضها
  `RecordValidator` ويسجّلها.
- يأخذ `ScatterPlotConfig` الوسائط `hover_data_columns` و`hover_template`
  و`color_continuous_scale` و`color_range` و`color_label` و`marker` و`layout`.
- يحصر `ValueClipStep` الأعمدة الرقمية أثناء المعالجة اللاحقة، ويرتّب `TableLayoutStep` الصفوف
  والأعمدة.
- استعلامات التقارب `NEAR(...)` في لغة الاستعلام، في صورة العقدة `Near` مع `NEAR_DISTANCE`، التي
  يدعمها مخزنا النصوص كلاهما، و`QueryChip.near`.
- مرشحات النطاقات: يُبقي `RangeFilter` السجلات التي تقع وسومها بين حدود صحيحة أو نصية، مثل
  السنوات أو تواريخ ISO 8601، في مخزنَي النصوص كليهما وفي البحث الهجين وفي `filter_graph`. وتعدّ
  `AsyncTextSearchStore.range_counts` المطابقات في كل نطاق من عدة نطاقات. ويسمّي `SearchFilter`
  أيًّا من نوعَي المرشحات.
- مقتطفات أغنى: تحمل `TextHit.snippets` و`FusedHit.snippets` كائن `Snippet` لكل حقل فيه مطابقة
  مُبرزة. وتبني `passage_snippet` و`snippet_window` مقتطفات لنصوص أخرى.
- تبني `backfill_text_index` فهرسًا نصيًا من المقاطع الموجودة في الذاكرة المتجهية، مُزيلةً الكلمات
  التي تتشاركها المقاطع المتداخلة (`merge_passages`)، وتُبلغ عما فعلته في `BackfillReport`.
  وتُخرج `AsyncEmbeddingStore.iter_records` مقاطع كل سجل في صورة `StoredRecord` دون تحميل
  المتجهات، وينفّذها المخزنان المضمّنان كلاهما.
- تُعيد `AsyncSimilarArticleFinder.find_best_chunks` أفضل مقطع لكل مقالة، مع نصه. ويوفّر
  `SlidingWindowChunker` القيمتين `chunk_words` و`overlap_words`.

### التغييرات {#changed_4}

- صار `PipelineConfig.max_records` هو `total_limit`، و`max_workers` هو `max_concurrency`. وتظل
  مفاتيح YAML والسمات القديمة تعمل مع `DeprecationWarning` حتى 0.5.0، وتحميل إعداد يضبط مفتاحًا
  قديمًا وآخر جديدًا على قيمتين مختلفتين يرفع `ConfigurationError`. وأُهمل `run(max_records=)`
  بالطريقة نفسها.
- أُهملت `build_retrying_session` وستُزال في 0.5.0، مع `requests` في الإضافة `full`.
- صارت نتيجة البحث الهجين التي لم يجدها إلا الفرع الدلالي تحمل مقتطفًا من أفضل مقاطعها في
  `snippet` و`highlights` و`snippets`، حيث كانت هذه فارغة من قبل. وينبغي للشيفرة التي كانت تعرض
  الملخص كلما كان `snippet` فارغًا أن تفحص `lexical_rank is None` بدلًا من ذلك.
- تنتظر `ETLPipeline.run` الحلقة الخلفية على فترات قصيرة، فيعمل معالج الإشارات على الخيط
  المستدعي بسرعة، ويُلغي `KeyboardInterrupt` التشغيل على الحلقة الخلفية.

## [0.3.0] - 2026-09-15 {#030-2026-09-15}

### الإضافات {#added_4}

- بحث بولياني محلي في `sci_etl_core.search`، لا يحتاج إلا إلى المكتبة القياسية:
  - لغة استعلام بمصطلحات، و`"عبارات"`، ومصطلحات بادئة `prefix*`، وتقييدات الحقول `title:`
    و`abstract:` و`body:`، و`AND` و`OR` و`NOT` (تُكتب أيضًا `&&` و`||` و`-`، أو لا يُكتب شيء
    في حالة `AND`)، والأقواس. تُعيد `parse_query` شجرة صياغة مجردة مُطبَّعة، ويرفع الاستعلام
    المشوّه `SearchQueryError`، الذي يحدد `position` و`token` فيه موضع الخطأ. وتحوّل `describe`
    الاستعلام إلى رقاقات للعرض.
  - `AsyncSqliteFts5Store`، فهرس نصي دائم على SQLite FTS5. يرتّب بـ BM25 مع أوزان لكل حقل
    `BM25Weights`، ويُعيد مقتطفات نصية عادية مع إزاحات الإبراز، ويصفّي حسب البيانات الوصفية
    (`MetadataFilter`)، ويعدّ الأوجه على `facet_keys` الخاصة به، ويوفّر `optimize`
    و`rebuild_index` و`rebuild_tags` و`integrity_check` للصيانة. وتُبلغ `fts5_available()` عما
    إذا كانت SQLite في المفسّر تتضمن FTS5.
  - `InMemoryTextSearchStore`، الذي يطابق السجلات نفسها التي يطابقها مخزن FTS5.
  - `AsyncSearchIndexer`، نظير `AsyncChunkIngestor` الخاص بالفهرس النصي.
  - دمج الترتيب بـ `reciprocal_rank_fusion`، وهو الافتراضي، أو `normalized_score_fusion`،
    ويُضبط بـ `FusionParams`.
  - `AsyncHybridSearcher`، الذي يشغّل بحثًا معجميًا أو دلاليًا أو هجينًا ويُبلغ في
    `SearchOutcome.degraded` و`SearchOutcome.skipped` عن فروع الاسترجاع التي فشلت أو لم يكن
    لديها ما تشغّله.
- رسوم الاستكشاف البيانية في `sci_etl_core.search`. تُنمّي `build_discovery_graph` جوار سجل
  بذرة عرضًا أولًا من مصدر حواف واحد أو أكثر، ولا تُبقي افتراضيًا إلا الجيران الأقرب المتبادلين،
  وتجمّع السجلات في مجتمعات بانتشار وسوم حتمي. ويحدّ `GraphParams` العمق والتفرع والحد الأدنى
  لوزن الحافة وعدد العقد وعدد تمريرات انتشار الوسوم، وتُبلغ
  `DiscoveryGraph.communities_converged` عما إذا كان حد التمريرات قد قطع انتشار الوسوم قبل
  اكتماله. وتضيّق `filter_graph` رسمًا مبنيًا إلى السجلات المطابقة ومرشحات البيانات الوصفية دون
  أي إدخال وإخراج. و`label_communities` و`select_edges` عامّتان أيضًا.
- مصادر حواف خلف واجهة جديدة `AsyncEdgeSource`. يربط `EmbeddingEdgeSource` السجلات بتشابه جيب
  التمام في الذاكرة المتجهية، ويربطها `MetadataEdgeSource` بنسبة الوسوم المشتركة بين سجلين، مثل
  تصنيفات arXiv والمؤلفين.
- `sci_etl_core.discovery`، نموذج قراءة لواجهات المستخدم: `Facet` و`DiscoveryResult`، المصدَّران
  أيضًا من `sci_etl_core`. واستيرادها لا يحمّل أي مخزن ولا أي اعتمادية اختيارية.
- `AsyncCompositeIngestor`، الذي يرسل كل سجل إلى عدة واجهات خلفية للذاكرة في وقت واحد، مثل الذاكرة
  المتجهية وفهرس نصي، فلا يوقف عطل الذاكرة في إحداها البقية.
- `MemoryIngestor`، البروتوكول الذي يحققه `memory_ingestor`، و`MEMORY_FAULTS`، الاستثناءات التي
  يعاملها خط المعالجة بوصفها أعطالًا في الذاكرة.
- `SearchError`، مع صنفيه الفرعيين `SearchQueryError` و`SearchStoreError`.
- الإضافة `search`. لا تثبّت شيئًا، لأن البحث لا يحتاج إلا إلى المكتبة القياسية؛ وإنما تتيح لملف
  المتطلبات أن يذكر سبب وجود الحزمة.

### التغييرات {#changed_5}

- يقبل `AsyncETLPipeline(memory_ingestor=)` أي `MemoryIngestor`. ويُسجَّل `SearchStoreError`
  أثناء الاستيعاب في الذاكرة، وتظل كيانات السجل تُصدَّر، كما في عطل التضمين. أما
  `SearchQueryError` فليس عطلًا في الذاكرة، ويُفشل السجل.
- لم تعد `RawRecord.metadata` فارغة لسجلات arXiv: إذ يملؤها `AsyncArxivExtractor` بالحقول
  `categories` و`authors` و`published` و`year`. وستلاحظ ذلك الشيفرة التي كانت تقارن
  `metadata == {}`. ولم تتغير البيانات الوصفية للمقاطع التي يخزّنها `AsyncChunkIngestor`.
- يعمل `AsyncSqliteEmbeddingStore` على منفّذ SQLite داخلي مشترك. وهذا لا يغيّر السلوك: فأنواع
  الاستثناءات ورسائلها والمعاملات والسلوك عند الإلغاء لم تتغير.

### الإصلاحات {#fixed_3}

- `AsyncSqliteStateManager`: لم يعد إلغاء مهمة تنتظر عملية على الحالة يحرر الاتصال بينما لا يزال
  خيطها العامل يستخدمه. وتنتظر العملية التالية انتهاء ذلك الخيط.

## [0.2.0] - 2026-09-14 {#020-2026-09-14}

### الأمان {#security}

- لم تعد `load_config` و`load_config_async` تنسخان نص خطأ pydantic إلى `ConfigurationError`. فقد
  كان ذلك النص قد يتضمن الإعدادات الخام، ومعها مفتاح واجهة برمجية مقروء من البيئة. وصارت الرسالة
  تسرد كل مفتاح فاشل وسببه دون قيمته، ولم يعد خطأ التحقق مسلسلًا بها.

### الإضافات {#added_5}

- تتحقق `validate_config(config_cls, raw, source)` من الإعدادات المحمّلة بطرق أخرى بالرسائل نفسها
  التي لا تكشف الأسرار.
- دعم `Retry-After`. ينتظر `AsyncArxivExtractor` و`AsyncOpenAICompatibleClient`
  و`AsyncOpenAIEmbedder` المدة التي تطلبها الاستجابة المخنوقة أو الفاشلة، عبر `Retry-After` أو
  الترويسة `retry-after-ms` التي ترسلها الواجهات المتوافقة مع OpenAI، متى كانت أطول من مدة
  تراجعها. ويحدّ الوسيط الجديد `max_retry_after` مدة الانتظار (60 ثانية افتراضيًا).
- يسجّل مستخرِج arXiv كل إعادة محاولة ومدة انتظارها.
- استهلاك الرموز. تُعيد `AsyncOpenAICompatibleClient.usage` و`AsyncOpenAIEmbedder.usage` لقطة
  `TokenUsage` تحوي `requests` و`prompt_tokens` و`completion_tokens` و`total_tokens`. وتُعيد
  الخاصية `usage` في `AsyncLLMClient` و`AsyncEmbedder` القيمة `None` ما لم يُعَد تعريفها.
- يعمل ruff وmypy في التكامل المستمر، وتثبّتهما الإضافة `lint` محليًا.
- سجل التغييرات هذا.

### التغييرات {#changed_6}

- عُطّلت إعادة المحاولة المدمجة في حزمة OpenAI SDK في عميلَي المحادثة والتضمينات، فصار
  `max_retries` هو العدد الإجمالي للمحاولات. وكانت الحزمة من قبل قد تعيد كل محاولة من تلك المحاولات
  بنفسها.
- تبدأ رسائل الإعدادات غير الصالحة بـ `Invalid configuration in <file>:` وتضع كل مشكلة في سطر
  مستقل.
- صار `AsyncETLPipeline.__aexit__` موسومًا بأنه يُعيد `None`، فتعرف أدوات فحص الأنواع أن
  `async with pipeline` لا يكتم أي استثناء أبدًا.

## [0.1.2] - 2026-09-14 {#012-2026-09-14}

### الإصلاحات {#fixed_4}

- كانت قيمة `max_concurrency` المساوية لـ 0 تُبقي كل سجل منتظرًا إلى الأبد. وصارت القيم الأقل من 1
  ترفع `ValueError`، وكذلك `page_size` الأقل من 1 و`total_limit` السالب.
- كان فشل سجل واحد في صفحة بقية سجلاتها غير ذات صلة يُجهض التشغيل كله. وصار التشغيل لا يُجهَض إلا
  حين تفشل صفحة ثانية دون معالجة أي شيء قبل أي تقدم، أو حين تنتهي القائمة مباشرة بعد صفحة كهذه.
- كان خط المعالجة ينتظر `sleep_between` مرة إضافية بعد بلوغ `total_limit`.
- كانت قيمة `max_retries` الأقل من 1 تجعل مستخرِج arXiv وعميل النموذج اللغوي ومولّد التضمينات
  يفشلون دون محاولة واحدة. وصارت ترفع `ValueError`.
- كانت `configure_logging` تفشل حين يكون مجلد ملف السجل مفقودًا، وتتجاهل ملفًا أو مستوى مختلفًا في
  الاستدعاءات اللاحقة.
- كان `AsyncFileStateManager` يحذف بصمت المسافات من معرّفات السجلات، فتُعالَج هذه السجلات من جديد
  في كل تشغيل. وصار يرفضها، ويتخطى خط المعالجة المعرّفات الفارغة.
- تُسجَّل `last_run_at` بتوقيت UTC مع إزاحة بدلًا من التوقيت المحلي المجرد من المنطقة الزمنية.

### الإضافات {#added_6}

- `PipelineConfig.page_size` و`PipelineConfig.search_delay`.
- التحقق من النطاقات لكل قسم من أقسام الإعداد.

### التغييرات {#changed_7}

- يرفع سير عمل الإصدار الملفات المبنية إلى إصدار GitHub موجود أصلًا بدلًا من الفشل.

## [0.1.1] - 2026-09-14 {#011-2026-09-14}

### الإضافات {#added_7}

- سير عمل إصدار يُطلقه وسم، يشغّل مجموعة اختبارات التكامل المستمر، ويقارن الوسم بإصدار المشروع،
  وينشر على PyPI بالنشر الموثوق.
- البيانات الوصفية للحزمة على PyPI: الترخيص والكلمات المفتاحية والمصنِّفات وعناوين URL للمشروع.

## [0.1.0] - 2026-09-13 {#010-2026-09-13}

أول إصدار موسوم: خط المعالجة غير المتزامن وواجهته المتزامنة، ومستخرِج arXiv، وعميلا محادثة
وتضمينات متوافقان مع OpenAI، ومحلِّلات PDF وLaTeX وHTML، ومصدِّرات CSV وSQL وPlotly، ومعالِجات
أُطُر البيانات ومدقّقاتها، والحالة في الملفات وفي SQLite، والذاكرة الدلالية، ودليل ترحيل
udg-catalogue.

[Unreleased]: https://github.com/xueromll/sci-etl-core/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/xueromll/sci-etl-core/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/xueromll/sci-etl-core/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/xueromll/sci-etl-core/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xueromll/sci-etl-core/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xueromll/sci-etl-core/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xueromll/sci-etl-core/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/xueromll/sci-etl-core/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/xueromll/sci-etl-core/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xueromll/sci-etl-core/releases/tag/v0.1.0
