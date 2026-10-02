# ترحيل خط معالجة

ينقل هذا الدليل خط معالجة بحثيًا قائمًا إلى `sci-etl-core`، مستخدمًا ترحيلًا حقيقيًا
واحدًا مثالًا تطبيقيًا: [udg-catalogue](https://github.com/xueromll/udg-catalogue)، الذي
يبني بنموذج لغوي فهرسًا للمجرات فائقة الانتشار (UDG) من أوراق arXiv.

كل مقتطف "قبل" مأخوذ من udg-catalogue كما كان قبل الترحيل. وكل مقتطف "بعد" في الخطوات من
1 إلى 9 مأخوذ من المشروع بعد ترحيله إلى sci-etl-core 0.2، عند
[الإيداع `8cd9471`](https://github.com/xueromll/udg-catalogue/tree/8cd94711b864212a8fa0d55d60f51e500cf42ec3).
وقد أُعيدت تسمية بعض استدعاءات 0.2 تلك أو أُزيلت منذ ذلك الحين. ويُظهر
[ما ستنتهي إليه](#where-youll-end-up) المشروع على 0.6، ويُظهر
[ترقية المشروع](#upgrading-the-project) كيف تغيّرت الشيفرة في
[الفرع `main`](https://github.com/xueromll/udg-catalogue/tree/main) للمشروع مع انتقاله إلى
0.4 و0.5 و0.6. ويسرد [دليل الترحيل](../project/migration.md) كل تغيير حسب الإصدار. العلم
هنا علم الفلك، لكن لا شيء في الخطوات يعتمد عليه: استبدل الموجِّهات والحقول وقواعد المجال
بما يخصك.

- [المشروع قبل الترحيل](#the-project-before)
- [ما ستنتهي إليه](#where-youll-end-up)
- [طابِق خط معالجتك مع المكتبة](#map-your-pipeline-onto-the-library)
- [الخطوة 1: ثبّت المكتبة واربطها](#step-1-install-and-link-the-library)
- [الخطوة 2: الإعداد والأسرار](#step-2-configuration-and-secrets)
- [الخطوة 3: المصدر والنص الكامل](#step-3-source-and-full-text)
- [الخطوة 4: خطوات النموذج اللغوي](#step-4-the-llm-steps)
- [الخطوة 5: قواعد المجال بوصفها إضافات](#step-5-domain-rules-as-plug-ins)
- [الخطوة 6: التصدير والحالة](#step-6-export-and-state)
- [الخطوة 7: المعالجة اللاحقة](#step-7-post-processing)
- [الخطوة 8: تحقق من تطابق النتائج قبل تغيير السلوك](#step-8-check-parity-before-changing-behavior)
- [الخطوة 9: احذف الشيفرة القديمة](#step-9-delete-the-old-code)
- [ترقية المشروع](#upgrading-the-project)
- [ما كشفه الترحيل](#what-the-migration-uncovered)
- [تكييف ذلك مع مجالك](#adapting-this-to-your-field)

---

## المشروع قبل الترحيل {#the-project-before}

يبحث udg-catalogue في arXiv عن `cat:astro-ph.GA AND abs:ultra-diffuse`. ولكل ورقة يسأل
نموذجًا لغويًا عما إذا كان الملخص يُبلغ عن أرصاد حقيقية، وينزّل مصدر LaTeX أو ملف PDF،
ويطلب من النموذج اللغوي استخراج كل مجرة بصيغة JSON، ويدمج المجرات في ملف CSV. ثم تُزيل
خطوة معالجة لاحقة التكرارات، وتقيّم الاكتمال، وتسند الكوكبات والعناقيد ثلاثية الأبعاد،
وتكتب الفهرس المرتب الذي تقوم عليه لوحة معلومات Streamlit.

كانت آلية ETL تعيش في وحدات مسطحة في جذر المشروع:

| الوحدة | الأسطر | المسؤولية |
|--------|--------|-----------|
| `arxiv_client.py` | 198 | البحث في arXiv وتحليل Atom، وتنزيل LaTeX وPDF، واستخراج الجداول، واقتطاع المراجع، واستدعاءا النموذج اللغوي كلاهما |
| `data_processor.py` | 314 | ملف المعرّفات المعالَجة، والتحقق من المجرات، والإدراج أو التحديث في CSV، وإزالة التكرار، والاكتمال، والكوكبات، والعنقدة، وعلامات الجودة |
| `main.py` | 94 | حلقة تنقل بين الصفحات فوق `ThreadPoolExecutor` |
| `config.py`، `logger.py`، `incremental.py` | 97 | قراءة YAML إلى ثوابت الوحدة، وإعداد التسجيل، وإزاحة الاستئناف |

بدت حلقة التنسيق في `main.py` هكذا:

```python
while papers_processed < MAX_PAPERS:
    xml_data = search_arxiv(SEARCH_QUERY, max_results=MAX_PAPERS, start_index=start_index)
    if not xml_data:
        break
    papers, total_in_xml = parse_arxiv_xml(xml_data, processed_ids)
    if total_in_xml == 0 or not papers:
        break

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_paper_task, paper, processed_ids): paper for paper in papers}
        for future in as_completed(futures):
            try:
                success = future.result()
                if success:
                    papers_processed += 1
                if papers_processed >= MAX_PAPERS:
                    break
            except Exception as exc:
                logger.error(f"Paper processing generated an exception: {exc}")

    start_index += MAX_PAPERS
    save_pipeline_metadata(start_index)
    time.sleep(SLEEP_BETWEEN)
```

## ما ستنتهي إليه {#where-youll-end-up}

بعد الترحيل يصبح جانب الاستيعاب كله بضع دوال تربط مكوّنات المكتبة معًا. هذا هو
`udg_catalogue/pipeline.py` على sci-etl-core 0.6، مختصرًا إلى خط الاستيعاب ودون المغلّفات
التي تسجّل التقدم:

```python
def build_catalogue_exporter(config: CatalogueConfig) -> AsyncCsvExporter:
    return AsyncCsvExporter(config.paths.raw_catalogue, [KEY_COLUMN, *MEASUREMENT_FIELDS])


def build_entity_extractor(
    config: CatalogueConfig,
    llm_client: AsyncLLMClient,
    rejections: AsyncRejectionStore | None = None,
) -> AsyncLLMEntityExtractor[dict[str, Any]]:
    return AsyncLLMEntityExtractor(
        llm_client,
        EXTRACTION_PROMPT,
        result_key=EXTRACTION_RESULT_KEY,
        timeout=config.llm.timeout,
        validator=build_galaxy_validator(),
        rejections=rejections,
        label_field=KEY_COLUMN,
    )


def build_pipeline(config, logger, http_client, llm_client, library, shutdown=None):
    cache = AsyncSqliteLLMResponseCache(config.paths.llm_cache)
    cached_llm = CachingLLMClient(llm_client, cache, model=config.llm.model)
    rejections = AsyncSqliteRejectionStore(config.paths.rejections)
    extractor = AsyncArxivExtractor.from_config(
        config.http,
        config.pipeline,
        client=http_client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        full_text=config.full_text,
    )
    return AsyncETLPipeline.from_config(
        config.pipeline,
        extractor=extractor,
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=cached_llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=build_entity_extractor(config, cached_llm, rejections),
        exporter=build_catalogue_exporter(config),
        state_manager=AsyncFileStateManager(config.paths.processed_ids, config.paths.pipeline_metadata),
        closeables=[http_client, llm_client, cache, rejections, *library.closeables],
        memory_ingestor=library.memory_ingestor(build_chunker(config.embeddings)),
        shutdown=shutdown,
        on_event=PipelineEventLogger(logger.info, logger.warning),
        usage_sources=[llm_client, *library.usage_sources],
    )


async def run_ingestion(config, logger, start_index=None, shutdown=None) -> int:
    library = open_paper_library(config)
    http_client = build_http_client(config)
    llm_client = build_llm_client(config)
    async with build_pipeline(config, logger, http_client, llm_client, library, shutdown) as pipeline:
        return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

تأخذ `build_pipeline` عميلَي HTTP والنموذج اللغوي وسيطين، فتمرر اختبارات المشروع
`httpx.MockTransport` يقدّم موجز Atom وملف e-print زائفين، إضافة إلى `AsyncLLMClient`
بإجابات معدّة مسبقًا، وتشغّل خط المعالجة الحقيقي دون اتصال.

ويتقلص `main.py` إلى تحميل الإعداد، وتشغيل الاستيعاب، وبناء المخرجات:

```python
config = load_catalogue_config(arguments.config)
log = configure_run_logging(config.paths.log_file)
processed = asyncio.run(run_ingestion(config, log, start_index, ShutdownSignal()))
catalogue = build_sorted_catalogue(config, log.info, replace=arguments.replace_catalogue)
write_manifest(config, log.info)
```

ما يبقى في المشروع هو الجزء الذي لا يكتبه إلا عالم فلك: الموجِّهات، وقواعد تسمية المجرات
والتحقق منها، والمطابقة حسب الموقع في السماء، والخصائص المستخدمة في العنقدة، ولوحة
المعلومات.

## طابِق خط معالجتك مع المكتبة {#map-your-pipeline-onto-the-library}

ابدأ بتصنيف كل دالة في خط المعالجة القديم في واحدة من ثلاث مجموعات: يستبدلها مكوّن من
المكتبة، أو يستبدلها مكوّن من المكتبة مع إضافة صغيرة، أو تبقى.

| قبل (udg-catalogue) | بعد | ما تظل تكتبه بنفسك |
|---------------------|-----|---------------------|
| `search_arxiv`، `parse_arxiv_xml` | `AsyncArxivExtractor` | لا شيء |
| `fetch_paper_text`، `extract_tables_from_pdf`، `trim_references` | `AsyncArxivExtractor` مع `LatexTarballParser` و`PdfPlumberParser` | لا شيء |
| جلسة `requests` مع `Retry` | `build_async_client` | لا شيء |
| `is_paper_relevant` | `AsyncLLMRelevanceFilter` | الموجِّه |
| `extract_udg_data` | `AsyncLLMEntityExtractor(result_key="galaxies")` | الموجِّه |
| عميل OpenAI موجَّه إلى DeepSeek | `AsyncOpenAICompatibleClient` | العنوان الأساسي والنموذج |
| `upsert_to_csv` | `AsyncCsvExporter`، ثم `DeduplicationStep` في المعالجة اللاحقة | قائمة الأعمدة |
| `load_processed_ids`، `save_processed_id`، `incremental.py` | `AsyncFileStateManager` | مسارات الملفات |
| حلقة `main.py` | `AsyncETLPipeline` | التوصيل الموضح أعلاه |
| `logger.py` | الوحدة القياسية `logging` | معالجات سجل التشغيل |
| `config.py` | صنف فرعي من `BaseAppConfig` و`load_config` | إعدادات المشروع |
| `universal_normalize_name` | صنف فرعي من `KeyNormalizer` | قواعد مطابقة الأسماء |
| `is_valid_galaxy` | مدقّقات `RecordValidator` ممرَّرة إلى `AsyncLLMEntityExtractor(validator=)` | قواعد الحقول |
| `clean_duplicates` | `NormalizationStep` و`DeduplicationStep` | `NeighborMatcher` لمواقع السماء |
| `calculate_completeness`، `assign_quality_flag` | `CompletenessStep`، `QualityFlagStep` | قائمة الحقول |
| `assign_3d_clusters` | `ClusteringStep` | `FeatureExtractor` للمواقع ثلاثية الأبعاد |
| `assign_constellations`، والرسوم، ولوحة المعلومات | تبقى | شيفرة المجال، في صورة `Processor` حيث يناسب |

يسمّي الجدول مكوّنات sci-etl-core 0.6. أما الخطوات من 1 إلى 9 فتُظهر مكوّنات 0.2 التي
استخدمها udg-catalogue آنذاك، مثل مصدِّر CSV يُدرج أو يحدّث ومغلّف مستخرِج يتحقق من
الكيانات، وقد استبدلتها إصدارات لاحقة.

## الخطوة 1: ثبّت المكتبة واربطها {#step-1-install-and-link-the-library}

ستغيّر قاعدتَي الشيفرة كلتيهما أثناء الترحيل، لذا ثبّت المكتبة بالوضع القابل للتحرير
في بيئة المشروع. يقع udg-catalogue على بُعد مجلدين من نسخته المستنسخة من sci-etl-core:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "../../sci-etl-core[async,llm,pdf,cluster]"
python -c "import sci_etl_core; print(sci_etl_core.__file__)"
```

في ويندوز فعّل البيئة بـ `.venv\Scripts\activate`. وينبغي أن يطبع الأمر الأخير مسارًا داخل
مجلد `src` في النسخة المستنسخة. اختر الإضافات الخاصة بالمكوّنات التي تستخدمها: يحتاج
udg-catalogue إلى `async` لمستخرِج arXiv ومصدِّر CSV، و`llm` للعميل المتوافق مع OpenAI،
و`pdf` لـ `PdfPlumberParser`، و`cluster` لـ `ClusteringStep`.

يسجّل التثبيت القابل للتحرير المسار المطلق للنسخة المستنسخة. فإن نقلت مجلد المكتبة أو
أعدت تسميته، فشل `import sci_etl_core` حتى تعيد التثبيت؛ وهذا بالضبط ما حدث حين انتقلت
مساحة عمل udg-catalogue إلى مجلد OneDrive متزامن.

لا ترى البيئات المنشورة نسخة مستنسخة مجاورة، ولا يستطيع pip تثبيت حزمة واحدة من مصدرين في
حلّ الاعتماديات نفسه. ولذلك يحتفظ udg-catalogue بحزم الطرف الثالث المثبّتة الإصدار في
`requirements-app.txt`، ويختار مصدر المكتبة في ملفين رقيقين. للتطوير المحلي،
`requirements-local.txt`:

```text
-r requirements-app.txt
-e ../../sci-etl-core[async,llm,pdf,cluster]
```

ولـ Docker والتكامل المستمر والمستخدمين الجدد، يثبّت `requirements.txt` الإصدار المنشور من
PyPI:

```text
-r requirements-app.txt
sci-etl-core[async,llm,pdf,cluster]>=0.2.0,<0.3
```

ثبّت نطاقًا من الإصدارات لا إصدارًا واحدًا بعينه، لتصل إصدارات إصلاح الأخطاء دون تغيير في
المشروع، وارفع الحد الأعلى عن قصد بعد اختبار الإصدار الفرعي الجديد بمجموعة اختباراتك. وقبل
أن تصبح المكتبة على PyPI، كان udg-catalogue يودع ملف wheel مبنيًا بـ
`pip wheel --no-deps -w vendor path/to/sci-etl-core` ويثبّته من `vendor/`؛ ولا يزال ذلك
يصلح لعملية بناء لا تصل إلى PyPI.

## الخطوة 2: الإعداد والأسرار {#step-2-configuration-and-secrets}

**قبل** (`config.py`): كان ملف YAML يُقرأ إلى ثوابت على مستوى الوحدة عند استيرادها.

```python
load_dotenv()
API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg: dict = yaml.safe_load(f)

MODEL: str = cfg.get("model", "deepseek-v4-flash")
CSV_FILE: str = os.path.join(SCRIPT_DIR, cfg.get("csv_file", "udg_database.csv"))
MAX_PAPERS: int = cfg.get("max_papers", 500)
```

**بعد**: يستخدم `config.yaml` أقسام المكتبة (`llm` و`http` و`pipeline`) إضافة إلى أقسام
المشروع الخاصة (`paths` و`clustering` و`deduplication`):

```yaml
llm:
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  timeout: 120

http:
  user_agent: "UDG-ResearchScript/1.0 (lanhua1122333@gmail.com)"
  max_retries: 4
  backoff_factor: 5.0
  timeout: 25

pipeline:
  search_query: "cat:astro-ph.GA AND abs:ultra-diffuse"
  max_records: 500
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_workers: 6

paths:
  raw_catalogue: "udg_database.csv"
  sorted_catalogue: "udg_database_sorted.csv"
  processed_ids: "processed_arxiv_ids.txt"
  pipeline_metadata: "pipeline_meta.json"

clustering:
  max_distance_mpc: 5.0
  min_samples: 2

deduplication:
  max_separation_arcsec: 3.0
```

يرث `udg_catalogue/config.py` نماذج المكتبة:

```python
class CataloguePipelineConfig(PipelineConfig):
    page_size: int = 100
    search_delay: float = 3.0


class CatalogueConfig(BaseAppConfig):
    pipeline: CataloguePipelineConfig = Field(default_factory=CataloguePipelineConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    deduplication: DeduplicationConfig = Field(default_factory=DeduplicationConfig)


def load_catalogue_config(config_path: Path = DEFAULT_CONFIG_PATH) -> CatalogueConfig:
    resolved = Path(config_path).resolve()
    config = load_config(
        CatalogueConfig,
        resolved,
        resolved.parent / ".env",
        api_key_env_var=API_KEY_ENV_VAR,
    )
    return config.model_copy(update={"paths": config.paths.anchored_at(resolved.parent)})
```

ثلاثة خيارات هنا تستحق النسخ:

- **احتفظ باسم سرّك.** يعني `api_key_env_var="DEEPSEEK_API_KEY"` أن ملف `.env` الموجود
  وملف Docker Compose يظلان يعملان دون تغيير. ويُحفظ المفتاح بوصفه `SecretStr`، فلا يظهر
  أبدًا في التمثيلات النصية ولا في السجلات.
- **وسّع الأقسام بالوراثة.** يضيف `CataloguePipelineConfig` الحقلين `page_size`
  و`search_delay` مع الإبقاء على كل حقل تقرؤه المكتبة.
- **حلّ المسارات انطلاقًا من ملف الإعداد.** تمرير ملف `.env` المجاور للإعداد صراحة،
  وتثبيت المسارات النسبية على مجلد الإعداد، يعنيان أن خط المعالجة يتصرف بالطريقة نفسها أيًّا
  كان الدليل الذي تبدأ منه. وكانت الشيفرة القديمة تحلّ معظم المسارات من مجلد السكربت، لكنها
  تحلّ `pipeline_meta.json` و`analysis/` من دليل العمل.

لا تُطبَّق قيم الإعداد تلقائيًا: مرّرها إلى المُنشئات وإلى `run()`، كما تفعل
`build_pipeline`.

## الخطوة 3: المصدر والنص الكامل {#step-3-source-and-full-text}

**قبل** (`arxiv_client.py`، مختصرًا):

```python
def search_arxiv(query: str, max_results: int = 5, start_index: int = 0) -> bytes | None:
    ...
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(base_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=(10, 60))
            if response.status_code == 429:
                time.sleep(20)
                continue
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(5 * (attempt + 1))
            else:
                logger.error(f"arXiv search failed after {MAX_RETRIES} attempts: {e}")
    return None


def fetch_paper_text(entry: dict) -> str:
    ...
    with session.get(source_url, headers={"User-Agent": USER_AGENT}, timeout=25, verify=False, stream=True) as r:
        ...
```

**بعد**:

```python
extractor = AsyncArxivExtractor(
    client=http_client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    max_retries=config.http.max_retries,
    backoff_factor=config.http.backoff_factor,
    sleep_before_search=config.pipeline.search_delay,
    logger=logger.info,
)
```

ما الذي تغيّر في السلوك:

- **البحث الفاشل خطأ، لا نهاية للبيانات.** كانت `search_arxiv` تُعيد `None`، فتعامل حلقة
  `main.py` ذلك على أنه "لا مزيد من الأوراق" وتمضي إلى الإبلاغ عن النجاح. ويُظهر السجل
  القديم 9 تشغيلات توقفت بهذه الطريقة. أما الآن فترفع `AsyncETLPipeline.run()` الاستثناء
  `PipelineAborted`، ويخرج `main.py` برمز الحالة 1.
- **تنتظر إعادات المحاولة أطول من القيم الافتراضية.** ينتظر المستخرِج
  `backoff_factor ** attempt` ثانية بين المحاولات، فينتظر المعامل الافتراضي 2 ثانية واحدة
  ثم ثانيتين. ويخنق arXiv بالرمز `429` مدة أطول من ذلك، وكانت الشيفرة القديمة تنتظر 20
  ثانية بعد 429، فيضبط udg-catalogue `backoff_factor: 5.0` و`max_retries: 4` (انتظار 1 و5
  و25 ثانية).
- **عاد التحقق من TLS.** كان تنزيل e-print القديم يستخدم `verify=False`.
- **مزيد من الإرسالات ينتج LaTeX.** يُقرأ ملف `.tex` واحد مضغوط بـ gzip بدلًا من الانتقال
  إلى PDF، وتُجمَّع المصادر متعددة الملفات بترتيب `\input`.
- **كل ما عدا ذلك على حاله.** أنماط اقتطاع المراجع هي التعابير السبعة نفسها، ويُلحق محلِّل
  PDF الجداول تحت العلامة نفسها `--- EXTRACTED TABLES ---`. وفي ثلاث أوراق حديثة أعادت
  الشيفرتان القديمة والجديدة نصًا متطابقًا بايتًا ببايت.

## الخطوة 4: خطوات النموذج اللغوي {#step-4-the-llm-steps}

**قبل** (`arxiv_client.py`، مختصرًا):

```python
def is_paper_relevant(title: str, abstract: str) -> bool:
    if not abstract:
        return True
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": STRICT_SIMULATION_PROMPT},
                {"role": "user", "content": f"Title: {title}\nAbstract: {abstract}"}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=20
        )
        data = json.loads(response.choices[0].message.content.strip())
        return bool(data.get("relevant", False))
    except Exception as e:
        logger.warning(f"Filter error: {e}. Proceeding to download.")
        return True


def extract_udg_data(text: str | bytes) -> list[dict]:
    try:
        ...
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return []
```

**بعد** (الاستدعاءات نفسها الموجودة في `run_ingestion` و`build_pipeline`، مستخرجة إلى
متغيرات):

```python
llm_client = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    default_timeout=config.llm.timeout,
)
relevance_filter = AsyncLLMRelevanceFilter(llm_client=llm_client, system_prompt=RELEVANCE_PROMPT)
entity_extractor = AsyncLLMEntityExtractor(
    llm_client=llm_client,
    system_prompt=EXTRACTION_PROMPT,
    result_key="galaxies",
    timeout=config.llm.timeout,
)
```

انتقلت الموجِّهات إلى `udg_catalogue/prompts.py` حرفًا بحرف. وكانت تذكر JSON أصلًا، وهو ما
يتطلبه وضع JSON، وكان موجِّه الاستخراج يطلب أصلًا `{"galaxies": [...]}`، فتقرأ
`result_key="galaxies"` هذا الشكل ولم يلزم تغيير الموجِّه. كما أن حد 120,000 محرف، وإزالة
HTML، ودرجة الحرارة 0، كلها قيم افتراضية في المكتبة أيضًا.

ما الذي تغيّر في السلوك:

- **ما زال مرشح الصلة يُمرّر عند الخطأ.** الاستدعاء الفاشل يُمرّر الورقة كما من قبل، والمهلة
  لا تزال 20 ثانية. ثمة فرق واحد: الرد الذي لا يحمل حكمًا واضحًا يُمرّر الورقة الآن أيضًا،
  بينما كانت الشيفرة القديمة تعدّ غياب المفتاح `relevant` مساويًا لـ `False`. مرّر
  `default_on_error=False` لحجز مثل هذه الأوراق بدلًا من ذلك؛ ومنذ 0.5.1 تُعاد عندئذ في
  التشغيل التالي.
- **يُعاد ما فشل استخراجه.** كانت `extract_udg_data` تُعيد `[]` حين يفشل DeepSeek، فتُعلَّم
  الورقة معالَجة دون استخراج أي شيء؛ ويُظهر السجل القديم 8 أوراق كهذه لن يُعاد إليها أبدًا.
  أما `AsyncLLMEntityExtractor` فيرفع `LLMError`، ويترك خط المعالجة الورقة دون تعليم، ويحاول
  التشغيل التالي معالجتها من جديد.

## الخطوة 5: قواعد المجال بوصفها إضافات {#step-5-domain-rules-as-plug-ins}

القواعد التي تقرر ما يُعدّ المجرة نفسها، وما يُعدّ مجرة حقيقية، علمٌ، وهي تبقى في المشروع.
وتمنحها المكتبة موضعًا تتصل به.

### مطابقة الأسماء: `KeyNormalizer` {#name-matching-a-keynormalizer}

**قبل** (`data_processor.py`):

```python
def universal_normalize_name(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    digits_match = re.search(r"\d+", s)
    if digits_match:
        digits = str(int(digits_match.group()))
        if s.startswith("vcc"):
            return f"vcc{digits}"
        return f"dragonfly{digits}"

    return s
```

انقل دالة كهذه **دون تغيير** أولًا، في صورة صنف فرعي من `KeyNormalizer`، كي لا يقارن فحص
التطابق في الخطوة 8 إلا البنية الموصِّلة ولا شيء غيرها. وهذا بالضبط ما فعله udg-catalogue.

وتبيّن أن هذه الدالة تدمج مجرات مختلفة (راجع [ما كشفه الترحيل](#what-the-migration-uncovered))،
فاستُبدلت بمجرد تأكيد تطابق النتائج. **بعد** (`udg_catalogue/naming.py`):

```python
DEFAULT_PREFIX_ALIASES: dict[str, str] = {"dragonfly": "df"}
_NAME_TOKEN = re.compile(r"[^\W\d_]+|\d+")
_NUMBER_SEPARATOR = "."


class GalaxyNameNormalizer(KeyNormalizer):
    def __init__(self, prefix_aliases: Mapping[str, str] | None = None) -> None:
        self._prefix_aliases = dict(DEFAULT_PREFIX_ALIASES if prefix_aliases is None else prefix_aliases)
        self._missing_value_guard = DefaultKeyNormalizer()

    def normalize(self, raw_value: Any) -> str:
        if not self._missing_value_guard.normalize(raw_value):
            return ""
        tokens = _NAME_TOKEN.findall(unicodedata.normalize("NFKC", str(raw_value)).casefold())
        if not tokens:
            return ""
        tokens[0] = self._prefix_aliases.get(tokens[0], tokens[0])
        key: list[str] = []
        previous_is_number = False
        for token in tokens:
            is_number = token.isdecimal()
            if is_number and previous_is_number:
                key.append(_NUMBER_SEPARATOR)
            key.append(str(int(token)) if is_number else token)
            previous_is_number = is_number
        return "".join(key)
```

ما زالت `DF 44` و`DF044` و`Dragonfly 44` تتشارك المفتاح `df44`، بينما تحتفظ الآن `KDG 44`
و`NGC 1052-DF2` و`NGC 1052-DF4` بمفاتيحها الخاصة. وتفويض فحص القيمة المفقودة إلى
`DefaultKeyNormalizer` يعني أن `None` و`NaN` والقيم غير العددية تُعامل بالطريقة التي يتوقعها
كل مكوّن في المكتبة. ويستخدم مصدِّر CSV وإزالة التكرار في المعالجة اللاحقة كلاهما
`GalaxyNameNormalizer`، فتتفق المرحلتان دائمًا على هوية الأجرام.

### التحقق: مدقّقات `RecordValidator` ومغلّف {#validation-recordvalidators-and-a-wrapper}

**قبل** (`data_processor.py`): كان التحقق مدفونًا داخل `upsert_to_csv`.

```python
def is_valid_galaxy(galaxy: dict) -> bool:
    ...
    if FORBIDDEN_PATTERN.search(name):
        logger.info(f"Object '{name}' filtered out as simulation/model.")
        return False

    ra, dec = galaxy.get("ra"), galaxy.get("dec")
    if ra is not None:
        try:
            if not (0.0 <= float(ra) <= 360.0):
                return False
        except (ValueError, TypeError):
            return False
    ...
    return any(galaxy.get(f) is not None for f in KEY_FIELDS)
```

**بعد** (`udg_catalogue/validation.py`): تغطي مدقّقات المكتبة قواعد الكلمات المفتاحية
والنطاقات، ويغطي صنف صغير واحد ما تبقى.

```python
class HasAnyMeasurement(RecordValidator):
    def __init__(self, fields: Iterable[str]) -> None:
        self._fields = tuple(fields)

    def is_valid(self, record: dict[str, Any]) -> bool:
        return any(record.get(field) is not None for field in self._fields)


def build_galaxy_validator() -> RecordValidator:
    return CompositeValidator(
        [
            KeywordExclusionValidator(KEY_COLUMN, list(SIMULATION_KEYWORDS)),
            NumericRangeValidator(SKY_COORDINATE_RANGES),
            HasAnyMeasurement(MEASUREMENT_FIELDS),
        ]
    )
```

لا يستدعي `AsyncETLPipeline` المدقّقات بنفسه، فيطبّقها `AsyncEntityExtractor` رقيق بين
الاستخراج والتصدير ويسجّل ما يحذفه:

```python
class ValidatedEntityExtractor(AsyncEntityExtractor):
    def __init__(
        self,
        inner: AsyncEntityExtractor,
        validator: RecordValidator,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self._inner = inner
        self._validator = validator
        self._log = logger or (lambda _message: None)

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        for entity in await self._inner.extract(text):
            if self._validator.is_valid(entity):
                accepted.append(entity)
            else:
                self._log(f"Entity rejected by validation: {entity.get(KEY_COLUMN)!r}")
        return accepted
```

قبل الاعتماد على `KeywordExclusionValidator` بدلًا من التعبير النمطي القديم، قارن بينهما على
بياناتك الحالية. ففي udg-catalogue اتفقا على كل الأسماء المخزنة البالغ عددها 1,285 وعلى
الحالات الحدية مثل `TNG50-1` و`illustris_galaxy_1` و`Firefly 7`.

## الخطوة 6: التصدير والحالة {#step-6-export-and-state}

**قبل** (`data_processor.py` و`incremental.py`، مختصرين): كان كل خيط عامل يقرأ ملف CSV
كله ويغيّره ويكتبه من جديد، دون أي قفل بين الخيوط الستة.

```python
def upsert_to_csv(records: list[dict]) -> None:
    ...
    df = pd.read_csv(CSV_FILE) if os.path.isfile(CSV_FILE) and os.path.getsize(CSV_FILE) > 0 else pd.DataFrame(columns=fieldnames)
    ...
    df.drop(columns=["_norm_name"]).to_csv(CSV_FILE, index=False, encoding="utf-8")


def save_processed_id(arxiv_id: str) -> None:
    if arxiv_id:
        with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
            f.write(arxiv_id + "\n")


def save_pipeline_metadata(start_index: int) -> None:
    meta = {"last_run_date": datetime.now().isoformat(), "last_start_index": start_index}
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4)
```

**بعد** (`build_catalogue_exporter` ومدير الحالة من `build_pipeline`، مع الثوابت من
`udg_catalogue/config.py` والمسارات الافتراضية مكتوبة صراحة):

```python
exporter = AsyncCsvUpsertExporter(
    key_column="galaxy_name",
    value_columns=["ra", "dec", "distance_mpc", "effective_radius_kpc", "stellar_mass_solar", "dark_matter_fraction"],
    normalizer=GalaxyNameNormalizer(),
    numeric_clip={"dark_matter_fraction": (0.0, 1.0)},
)
state_manager = AsyncFileStateManager("processed_arxiv_ids.txt", "pipeline_meta.json")
```

يحتفظ المصدِّر بقاعدة الدمج القديمة: صف واحد لكل اسم مُطبَّع، والسجلات اللاحقة لا تملأ إلا
الخلايا الفارغة، وتُحوَّل القيم إلى أعداد عشرية، وتحل `numeric_clip` محل الحصر المكتوب يدويًا
لكسر المادة المظلمة. كما يُسلسِل عمليات التصدير المتزامنة وينشر كل لقطة بإعادة تسمية ذرّية.

**تحقق مما إذا كان يمكن إعادة استخدام ملفات حالتك الحالية كما هي.** كان ذلك ممكنًا في
udg-catalogue: فقد كان `processed_arxiv_ids.txt` يحوي أصلًا معرّفات مجردة بإصداراتها مثل
`2607.14209v1`، وهو التنسيق الذي ينتجه `AsyncArxivExtractor`، وكان في `pipeline_meta.json`
أصلًا المفتاحان `last_run_date` و`last_start_index` اللذان يقرؤهما `AsyncFileStateManager`.
وتوجيه مدير الحالة إلى الملفات القديمة نقل كل الأوراق المعالَجة البالغ عددها 542 دون أي سكربت
استيراد. وإن كانت معرّفاتك مخزنة في صورة عناوين URL أو دون لاحقة الإصدار، فحوّلها أولًا، وإلا
عولجت كل ورقة من جديد.

تغيّر تفصيلان في الاستئناف:

- **القوائم المرتبة من الأحدث.** يسرد arXiv أحدث الإرسالات أولًا، فتنزاح الإزاحة المحفوظة
  مع وصول أوراق جديدة. أما الآن فيمرر `main.py` افتراضيًا `start_index=0`، فيعيد المسح من
  أحدث إرسال متخطيًا الأوراق المعالَجة حسب المعرّف؛ وإعادة المسح لا تكلّف إلا طلبات قوائم، لا
  استدعاءات للنموذج اللغوي. ويستخدم `python main.py --resume` الإزاحة المحفوظة بدلًا من ذلك.
- **لا تتقدم الإزاحات إلا بعد الصفحات المسوّاة.** كانت الحلقة القديمة تضيف 500 إلى الإزاحة بعد
  كل صفحة، حتى لو فشلت أوراق فيها. أما المكتبة فلا تتقدم إلى ما بعد صفحة إلا بعد أن تُعالَج
  كل ورقة فيها أو يُحكم بأنها غير ذات صلة.

## الخطوة 7: المعالجة اللاحقة {#step-7-post-processing}

**قبل** (`data_processor.py`، مختصرًا): كانت إزالة التكرار تعيد كتابة ملف CSV الخام في
مكانه بعد أخذ نسخة `.bak`، وكانت `process_database` تشغّل سلسلة من الدوال.

```python
def process_database() -> None:
    df = pd.read_csv(CSV_FILE)
    ...
    if "dark_matter_fraction" in df.columns:
        df["dark_matter_fraction"] = df["dark_matter_fraction"].clip(0.0, 1.0)

    df = calculate_completeness(df)
    df = assign_constellations(df)
    df = assign_3d_clusters(df)
    df = assign_quality_flag(df)
    ...
    df_sorted.to_csv(SORTED_CSV_FILE, index=False, encoding="utf-8")
```

**بعد** (`udg_catalogue/postprocess.py`): السلسلة نفسها في صورة `ProcessorChain`، مع ترك
ملف CSV الخام دون مساس وكتابة الفهرس المرتب وحده.

```python
def build_catalogue_chain(config: CatalogueConfig, normalizer: KeyNormalizer | None = None) -> ProcessorChain:
    return ProcessorChain(
        [
            NormalizationStep(KEY_COLUMN, normalizer or GalaxyNameNormalizer(), NORMALIZED_KEY_COLUMN),
            DeduplicationStep(
                NORMALIZED_KEY_COLUMN,
                matcher=SkyPositionMatcher(),
                match_threshold=config.deduplication.max_separation_arcsec,
            ),
            ValueClipStep(FRACTION_BOUNDS),
            CompletenessStep(list(MEASUREMENT_FIELDS)),
            ConstellationStep(),
            ClusteringStep(
                CartesianDistanceFeatures(),
                eps=config.clustering.max_distance_mpc,
                min_samples=config.clustering.min_samples,
            ),
            QualityFlagStep(),
            CatalogueLayoutStep(),
        ]
    )
```

`CompletenessStep` و`QualityFlagStep` و`NormalizationStep` و`DeduplicationStep`
و`ClusteringStep` تأتي من المكتبة. ويتصل العلم عبر واجهتين صغيرتين. يخبر
`SkyPositionMatcher` الخطوة `DeduplicationStep` بالصفوف التي تمثل الجرم نفسه في السماء:

```python
class SkyPositionMatcher(NeighborMatcher):
    def find_matches(self, frame: pd.DataFrame, threshold: float) -> list[tuple[int, int]]:
        located = frame[located_rows(frame, self._ra_column, self._dec_column)]
        if len(located) < 2:
            return []
        coordinates = sky_coordinates(located, self._ra_column, self._dec_column)
        neighbours, separations, _ = coordinates.match_to_catalog_sky(coordinates, nthneighbor=2)
        separation_arcsec = separations.to_value(u.arcsec)
        labels = located.index.to_numpy()
        return [
            (int(labels[position]), int(labels[neighbour]))
            for position, neighbour in enumerate(neighbours)
            if separation_arcsec[position] <= threshold and labels[position] < labels[neighbour]
        ]
```

يعطي `CartesianDistanceFeatures` الخطوة `ClusteringStep` مواقع ثلاثية الأبعاد مبنية من
المطلع المستقيم والميل والمسافة. أما `ConstellationStep` و`ValueClipStep`
و`CatalogueLayoutStep` فمعالِجات `Processor` عادية تبقى في المشروع: فلا يُطلب من `Processor`
إلا أن يُعيد DataFrame جديدًا دون تعديل مدخله.

إبقاء ملف CSV الخام مصدرَ الحقيقة للمصدِّر، واشتقاق الملف المرتب منه، يجعل المعالجة اللاحقة
قابلة للتكرار: يعيد `python main.py --skip-ingestion` بناء كل المخرجات دون الاتصال بـ arXiv
ولا بالنموذج اللغوي.

## الخطوة 8: تحقق من تطابق النتائج قبل تغيير السلوك {#step-8-check-parity-before-changing-behavior}

أبقِ الشيفرة القديمة قابلة للتشغيل بجوار الجديدة وغذِّ كلتيهما بالمدخلات نفسها. ولا تحتاج
إلى تثبيت المشروع القديم: صدّر الوحدات القديمة من Git إلى مجلد مؤقت بـ
`git show <commit>:data_processor.py`، واستوردها من هناك.

أجرى udg-catalogue أربعة فحوص.

**إعادة تشغيل التصدير.** قُسّم كل صف من الفهرس الحالي عشوائيًا إلى سجلي استخراج جزئيين،
وأُضيفت بضعة سجلات غير صالحة مكتوبة يدويًا، ثم غُذّيت السجلات المخلوطة على دفعات عبر الإدراج
أو التحديث القديم وعبر المدقّق والمصدِّر الجديدين:

```python
for batch in batches:
    data_processor.upsert_to_csv([dict(record) for record in batch])

for batch in batches:
    await exporter.export([record for record in batch if validator.is_valid(record)], "new.csv")
```

**المعالجة اللاحقة.** شُغّلت `clean_duplicates` و`process_database` القديمتان والسلسلة
الجديدة على نسخ من الفهرس الخام نفسه، وقورنت المخرجات المرتبة خلية بخلية. قارن *عضوية*
العناقيد لا معرّفاتها: فخوارزمية DBSCAN ترقّم العناقيد بترتيب مصادفتها لها.

**النص الكامل.** جلب الاسترجاعان القديم والجديد الأوراق الحديثة الثلاث نفسها.

**التشغيل الحي.** شُغّل خط المعالجة المجمَّع على arXiv وDeepSeek بقيم صغيرة لـ `page_size`
و`total_limit`، في مجلد حالة جديد.

| الفحص | النتيجة |
|-------|---------|
| إعادة تشغيل التصدير: 2,581 سجلًا في 735 دفعة | ملف CSV متطابق |
| إعادة تشغيل التصدير مع مجرة مكررة داخل ورقة واحدة | متطابق بعد دمج صفين مكررين أنشأهما الإدراج أو التحديث القديم |
| المعالجة اللاحقة لفهرس من 1,285 مجرة | متطابق خلية بخلية، بما في ذلك ترتيب الصفوف ومعرّفات العناقيد، باستثناء 3 صفوف يتجاوز فيها المطلع المستقيم 360° |
| النص الكامل لـ 3 أوراق حديثة | نص LaTeX متطابق بايتًا ببايت |
| التشغيل الحي | أجاب arXiv بـ `429` عن كل محاولة لجلب القائمة، ورفعت `run()` الاستثناء `PipelineAborted` دون كتابة أي شيء، بدلًا من الإبلاغ عن النجاح؛ وهذا ما دفع إلى إطالة التراجع في الخطوة 3 |
| مجموعة اختبارات المشروع | 84 اختبارًا تعمل دون اتصال، وتغطية 100%، تنجح مع المكتبة القابلة للتحرير ومع بيئة نظيفة مثبّتة من ملف wheel المودَع في المستودع |

ولم يُدخل إصلاح المُطبِّع إلا بعد أن تطابق كل ذلك، بوصفه تغييرًا منفصلًا. وعند إعادة توليد
الفهرس المرتب به، لم تكن الفروق سوى الصفوف الثلاثة ذات المطلع المستقيم غير الصالح، وعناقيد
أُعيد ترقيمها دون تغيّر في عضويتها، والعمود `filled_fields` المحذوف.

حين تشغّل خط المعالجة بعد ترحيله:

- ابحث في السجل عن `Record processing failed`. فهذه السجلات لم تُعلَّم معالَجة، وسيعيدها
  التشغيل التالي.
- إن رفعت `run()` الاستثناء `PipelineAborted`، فاقرأ `__cause__` الخاص به: يظهر هناك مفتاح
  واجهة برمجية مرفوض، أو ملف CSV غير قابل للقراءة، أو طلب قائمة مخنوق.
- إن كتبت مكوّناتك الخاصة، فقارنها بالعقود في
  [إضافة مكوّن جديد](../project/contributing.md#adding-a-new-component).

## الخطوة 9: احذف الشيفرة القديمة {#step-9-delete-the-old-code}

بعد نجاح الفحوص، احذف ما استبدلته المكتبة. أزال udg-catalogue الملفات `arxiv_client.py`
و`data_processor.py` و`config.py` و`logger.py` و`incremental.py`، ونمط كلمات المحاكاة
المكرر، وموجِّه المرشح غير المستخدم، مع الاختبارات التي كانت تحاكي `requests` ومجمّع الخيوط.
وما يبقى حزمة `udg_catalogue` من وحدات المجال (الإعداد، والموجِّهات، والتسمية، والتحقق،
والقياسات الفلكية، والمعالجة اللاحقة، والخرائط، والتحليلات)، ومجموعة اختبارات تشغّل خط
المعالجة الحقيقي دون اتصال.

كان `visualization.py` ولوحة المعلومات يبنيان شكل Plotly نفسه مرتين؛ فكان الترحيل لحظة مناسبة
لمنحهما بانيًا مشتركًا واحدًا للأشكال. ولم يُستخدم `AsyncPlotly3DExporter`، لأن خريطة
udg-catalogue تحتاج إلى نص تلميح مخصص ونطاق ألوان ثابت.

## ترقية المشروع {#upgrading-the-project}

تثبّت الخطوة 1 نطاقًا من الإصدارات ولا ترفع حده الأعلى إلا بعد اختبار الإصدار الفرعي الجديد
بمجموعة اختبارات المشروع. ويسرد [دليل الترحيل](../project/migration.md) ما يغيّره كل إصدار؛
ويسجّل هذا القسم ما عنته تلك التغييرات لـ udg-catalogue.

### الانتقال إلى 0.4 {#moving-to-04}

تخطّى udg-catalogue الإصدار 0.3: فلم تكن `build_pipeline` الخاصة به تمرر
`memory_ingestor`، ولم يتغير `AsyncFileStateManager`، فلم يؤثر فيه شيء في 0.3. وانتقل من
`>=0.2.0,<0.3` مباشرة إلى `>=0.4.0,<0.5`، مضيفًا الإضافات `embeddings` و`embeddings-local`
و`search`:

```text
sci-etl-core[async,llm,pdf,cluster,embeddings,embeddings-local,search]>=0.4.0,<0.5
```

أغنت الترقية إلى 0.4 عن عدة أجزاء من الشيفرة جعلت الخطوات السابقة المشروع يكتبها:

- **إعدادات خط المعالجة المعاد تسميتها.** تُصدر `build_pipeline` و`run_ingestion` من 0.2
  تحذيرات على 0.4، لأن `max_records` و`max_workers` صارا `total_limit` و`max_concurrency`.
  وأعاد udg-catalogue تسمية المفتاحين في `config.yaml`.
- **لا صنف فرعي لخط المعالجة.** اكتسب `PipelineConfig` الحقول `page_size` و`search_delay`
  و`newest_first`، فحُذف `CataloguePipelineConfig` من الخطوة 2، وصار `CatalogueConfig`
  يستخدم قسم `pipeline` في المكتبة كما هو.
- **التحقق دون مغلّف.** يمرر udg-catalogue `build_galaxy_validator()`
  و`label_field=KEY_COLUMN` إلى `AsyncLLMEntityExtractor`، وحذف `ValidatedEntityExtractor`
  من الخطوة 5.
- **الاستئناف من الأحدث.** يضبط udg-catalogue `pipeline.newest_first: true`، فصار
  `python main.py` يستأنف افتراضيًا؛ واختفى الخيار `--resume` من الخطوة 6، ويمرر `--rescan`
  القيمة `start_index=0` مع `newest_first=False` لتصفح القائمة كلها.
- **التخزين المؤقت والإيقاف وملخصات التشغيل.** يغلّف udg-catalogue عميل النموذج اللغوي في
  `CachingLLMClient` مدعوم بـ `AsyncSqliteLLMResponseCache`، فلا تدفع إعادة التشغيل بعد انهيار
  ثمن استدعاءات الصلة والاستخراج نفسها مرتين. ويمرر `ShutdownSignal`، ويخرج `main.py` بالرمز
  130 عند `PipelineInterrupted`. وتسجّل دالة رد النداء `on_event` كل `PageFinished`، ويصبح
  `RunMetrics` الخاص بحدث `RunFinished`، بما فيه استهلاك الرموز من `usage_sources`، ملخص
  التشغيل في السجل.
- **الرسوم.** اكتسب `ScatterPlotConfig` نص التلميح المخصص ونطاق الألوان الثابت اللذين منعا
  udg-catalogue من استخدام `AsyncPlotly3DExporter` في الخطوة 9.
- **الحصر وتخطيط الجدول.** حذف udg-catalogue الخطوتين `ValueClipStep` و`CatalogueLayoutStep`
  الخاصتين به من الخطوة 7؛ وصارت السلسلة تستورد `ValueClipStep` من المكتبة وتنتهي بـ
  `TableLayoutStep(sort_by=SORT_ORDER, leading_columns=LEADING_COLUMNS,
  hidden_prefixes=("_",))`.

بعد الترقية صارت شيفرة توصيل خط المعالجة في udg-catalogue تقرأ إعداداتها من ملف الإعداد
وتفهرس كل ورقة ذات صلة للبحث. ومختصرًا إلى فرع الاستيعاب، يبني `udg_catalogue/pipeline.py`
خط المعالجة هكذا:

```python
def build_pipeline(config, logger, http_client, llm_client, library, shutdown=None):
    cache = AsyncSqliteLLMResponseCache(config.paths.llm_cache)
    cached_llm = CachingLLMClient(llm_client, cache, model=config.llm.model, logger=logger.warning)
    extractor = AsyncArxivExtractor.from_config(
        config.http,
        config.pipeline,
        client=http_client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        logger=logger.info,
    )
    return AsyncETLPipeline.from_config(
        config.pipeline,
        extractor=extractor,
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=cached_llm, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=build_entity_extractor(config, cached_llm, logger),
        exporter=build_catalogue_exporter(),
        state_manager=AsyncFileStateManager(config.paths.processed_ids, config.paths.pipeline_metadata),
        destination=str(config.paths.raw_catalogue),
        logger=logger.warning,
        closeables=[http_client, llm_client, cache, *library.closeables],
        memory_ingestor=library.memory_ingestor(build_chunker(config.embeddings), logger.warning),
        shutdown=shutdown,
        on_event=progress_logger(logger.info),
        usage_sources=[llm_client, *library.usage_sources],
    )
```

تُعيد `library.memory_ingestor` كائن `AsyncCompositeIngestor` يخزّن المقاطع المضمَّنة في
`AsyncSqliteEmbeddingStore` ويفهرس الورقة في `AsyncSqliteFts5Store`، أو `AsyncSearchIndexer`
وحده حين تكون `embeddings.enabled` مساوية لـ false. ويتقلص التشغيل نفسه إلى كتلة
`async with` واحدة:

```python
async def _run(build, config, logger, start_index, shutdown):
    library = open_paper_library(config)
    http_client = build_http_client(config)
    llm_client = build_llm_client(config)
    async with build(config, logger, http_client, llm_client, library, shutdown) as pipeline:
        return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

لم تُفهرَس الأوراق التي فُرزت قبل الترقية قط، ولم تكن لدى udg-catalogue ذاكرة متجهية يُملأ
منها الفهرس. فيجلبها `python main.py --index-papers` من جديد عبر خط المعالجة نفسه، مع مستخرِج
كيانات لا يُعيد شيئًا، ومرشح صلة يتخطى الأوراق الموجودة أصلًا في الفهرس النصي، ومدير حالة
مستقل (`indexed_arxiv_ids.txt`، `indexing_meta.json`)، فيبقى فهرس المجرات ومعرّفاته المعالَجة
دون مساس.

### الانتقال إلى 0.5 {#moving-to-05}

انتقل udg-catalogue إلى `>=0.5.1,<0.6`. وقد مسّه تغييران:

- **إعداد صارم.** ترفض أقسام الإعداد في المكتبة المفاتيح المجهولة، وجعل udg-catalogue أقسامه
  الخاصة (`paths` و`embeddings` و`clustering` و`deduplication`) صارمة كذلك، فيفشل أي خطأ
  إملائي في `config.yaml` عند بدء التشغيل مع اسم المفتاح. ولم تعد تُحمَّل الأسماء
  `max_records` و`max_workers` من 0.2.
- **صفحات قوائم محلَّلة.** تُعيد المستخرِجات `ListingPage` من
  `fetch_page(query, cursor, page_size)` بدلًا من بايتات خام من `search` و`parse_listing`،
  فصار مغلّف المشروع الذي يسجّل كل طلب قائمة يمرر `cursor_for_offset` و`fetch_page` بدلًا من
  ذلك.

### الانتقال إلى 0.6 {#moving-to-06}

انتقل udg-catalogue إلى `>=0.6.0,<0.7`. ومنذ 0.6 لا يحتاج التثبيت الأساسي إلا إلى Pydantic،
فيسرد المشروع كل إضافة يستوردها، مضيفًا `config` (YAML و`.env`) و`arxiv` (تحليل Atom)
و`html` و`processors` (pandas):

```text
sci-etl-core[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]>=0.6.0,<0.7
```

وغيّرت بقية الترقية ما يسجّله الفهرس:

- **صف واحد لكل مجرة في كل ورقة.** اختفى `AsyncCsvUpsertExporter`. ويكتب `AsyncCsvExporter`
  صفًا لكل مجرة موسومًا بـ `record_id` الخاص بالورقة، ولا يدمج قيمة ولا يقتطعها ولا يحوّلها
  أبدًا، ويستبدل صفوف الورقة حين تُستخرج مرة أخرى. وانتقل الدمج كله إلى المعالجة اللاحقة.
  ولا يحوي الفهرس الخام الذي كتبه 0.5 عمود `record_id`، فيُعاد بناء الفهرس من الصفر مرة واحدة،
  وترفض المعالجة اللاحقة الملف الخام القديم برسالة توضح ذلك.
- **الأوراق التي تقف خلف كل مجرة.** تبدأ سلسلة المعالجة اللاحقة بخطوة صغيرة `RawRowsStep`
  تخفي `record_id` و`extra` باسمَي `_record_id` و`_extra` وتقرأ القياسات أعدادًا. ثم تسرد
  `DeduplicationStep(source_column="_record_id", sources_column="source_papers")` في الفهرس
  المنشور الأوراق المدموجة في كل مجرة.
- **رفض مع أسبابه، محفوظ للمراجعة.** تُعيد `GalaxyValidator.validate` كائن `Violation` يسمّي
  رمزه القاعدة المخروقة (`no-name` أو `paper-local-name` أو `simulation-keyword` أو
  `not-a-number` أو `not-positive` أو `out-of-range` أو `no-measurement`)، حيث لم تكن
  `is_valid` تقول سوى `False`. ويسجّل المستخرِج كل رفض مع سببه ويخزّنه في
  `AsyncSqliteRejectionStore`، حيث يستطيع المراجع سرده والبت فيه.
- **تسجيل قياسي.** اختفت وسائط `logger=` و`configure_logging`. وتربط
  `configure_run_logging` في المشروع معالجات سجل التشغيل بمسجِّل المشروع الخاص وبـ
  `sci_etl_core`، ويضيف `logging.Filter` إلى أسطر المكتبة بادئة بمعرّف arXiv للورقة قيد
  المعالجة.
- **الفهرسة لا تمس الفهرس أبدًا.** كان تشغيل `--index-papers` يمرر مصدِّر الفهرس مع مستخرِج
  لا يُعيد شيئًا. ومنذ 0.6 يكتب خط المعالجة كل سجل معالَج، بما فيه السجل الذي لا كيانات له،
  وكتابة كهذه تمسح صفوف تلك الورقة. ولذلك يحصل خط الفهرسة على مصدِّر لا يحتفظ بشيء:

    ```python
    class DiscardingExporter(AsyncExporter[Any]):
        async def write(self, record: RawRecord, entities: Sequence[Any]) -> None:
            return None
    ```

- **بيان التشغيل.** بعد كل بناء تسجّل `write_manifest` في `data/run_manifest.json` إصدار
  sci-etl-core، والنموذج والعنوان الأساسي، وتجزئتَي الموجِّهين، والاستعلام، ومعرّفات arXiv
  المعالَجة، وعدد الصفوف وقيمة SHA-256 للفهرسين؛ ويُودَع هذا الملف بجوار الفهرس المنشور.

## ما كشفه الترحيل {#what-the-migration-uncovered}

نقل الشيفرة إلى مكوّنات مشتركة يجبرك على صياغة كل قاعدة بدقة. وقد أظهر ترحيل udg-catalogue
هذه المشكلات، وكان معظمها خفيًا في المخرجات القديمة:

1. **كانت مطابقة الأسماء تدمج مجرات مختلفة.** كان المُطبِّع القديم يجعل مفتاح أي اسم يحوي
   أرقامًا، عدا أسماء VCC، هو `dragonfly<أول عدد>`: 1,201 اسمًا من أصل 1,285 اسمًا مخزنًا
   (93%). فطابق `KDG 44` الاسم `DF 44`، وطابق `NGC 1052-DF2` الاسم `NGC 1052-DF4`، فكان
   الإدراج أو التحديث يملأ بصمت ثغرات مجرة بقياسات مجرة أخرى. ويُبقي المُطبِّع المصحح كل
   الأسماء المخزنة البالغ عددها 1,285 متمايزة، لكن الصفوف التي دمجتها تشغيلات سابقة لا يمكن
   فصلها إلا بإعادة استخراج الفهرس.
2. **بدت الإخفاقات نجاحًا.** أنهت تسعة إخفاقات في بحث arXiv التشغيلات كأن القائمة استُنفدت،
   وعلّمت 8 أخطاء من DeepSeek أوراقًا معالَجة دون استخراج أي شيء.
3. **لم يكن لكتابات CSV المتزامنة قفل.** كانت ستة خيوط تعيد كتابة ملف CSV نفسه، ويسجّل السجل
   8 استثناءات من الخيوط العاملة في تلك الحلقة.
4. **كان التحقق من TLS معطّلًا** في تنزيلات e-print.
5. **كان الإدراج أو التحديث يكرر المجرات** المذكورة مرتين في استخراج ورقة واحدة، ولم يكتشف
   ذلك إلا إعادة تشغيل التصدير.
6. **لثلاث مجرات مخزنة مطلع مستقيم يتجاوز 360°.** كانت خطوة الكوكبات القديمة تلفّها بصمت؛
   أما الآن فيُبلَّغ عنها بوصفها `Unknown`.
7. **تعذّر تثبيت إصدارات الاعتماديات المثبّتة** على إصدار بايثون الذي ذكره README: فليس لـ
   `numpy==1.22.0` ملفات wheel لبايثون 3.11، و`pandas==2.0.0` يحتاج هناك إلى numpy أحدث.
8. **تعطّل التثبيت القابل للتحرير** بعد انتقال مساحة العمل إلى مجلد آخر.

## تكييف ذلك مع مجالك {#adapting-this-to-your-field}

- [ ] اسرد كل دالة في خط معالجتك وصنّفها في المجموعات الثلاث الواردة في
      [طابِق خط معالجتك مع المكتبة](#map-your-pipeline-onto-the-library).
- [ ] ثبّت المكتبة بالوضع القابل للتحرير، وقرر كيف ستحصل عليها بيئات النشر (نطاق إصدارات من
      PyPI، أو ملف wheel مودَع في المستودع حيث يتعذّر الوصول إلى PyPI).
- [ ] انقل الإعدادات إلى أقسام `BaseAppConfig`؛ واحتفظ باسم متغير البيئة الخاص بمفتاح واجهتك
      البرمجية عبر `api_key_env_var`.
- [ ] انقل الموجِّهات دون تغيير، واضبط `result_key` على مفتاح القائمة الذي يطلبه موجِّه
      الاستخراج أصلًا.
- [ ] انقل قاعدة مطابقة الأسماء بوصفها `KeyNormalizer` وقواعد السجلات بوصفها `RecordValidator`،
      دون تغيير في البداية.
- [ ] تحقق مما إذا كانت ملفات المعرّفات المعالَجة والإزاحة لديك تطابق أصلًا تنسيق مدير الحالة
      قبل كتابة سكربت استيراد.
- [ ] عبّر عن المعالجة اللاحقة في صورة `ProcessorChain`، مع وضع منطق مجالك في إضافات
      `NeighborMatcher` و`FeatureExtractor` و`Processor`.
- [ ] أعد تشغيل بيانات حقيقية عبر الشيفرتين القديمة والجديدة وقارن المخرجات.
- [ ] ثم أصلح فقط القواعد التي وجدتها قاصرة، إيداعًا واحدًا في كل مرة.
- [ ] احذف الشيفرة القديمة والاختبارات التي لم تكن تغطي سواها.

أسئلة أو موضع خشن في ترحيلك؟ افتح [مشكلة](https://github.com/xueromll/sci-etl-core/issues)،
ويسعدنا أن نساعد.
