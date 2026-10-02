# التثبيت

يلزم Python 3.11 أو أحدث.

```bash
pip install "sci-etl-core[async,arxiv,llm,pdf]"   # كل ما يستخدمه البدء السريع
pip install "sci-etl-core[full]"                  # كل المكوّنات المضمّنة عدا التضمينات المحلية
```

من نسخة مستنسخة من المستودع:

```bash
pip install -e ".[full]"
```

لا يتطلب التثبيت الأساسي سوى Pydantic. ويشمل خطَّي المعالجة كليهما، والإيقاف
السلس، وأحداث التقدم ومقاييس التشغيل، وعقود المكوّنات، ونماذج الإعداد، والواجهات
الخلفية للحالة، والتخزين المؤقت لاستجابات النموذج اللغوي، ومصدِّرَي CSV وJSON Lines،
والادعاءات ومصدرها، ومدقّقات السجلات، وتحليل LaTeX، وتقطيع النصوص، والبحث النصي
البولياني، ودمج الترتيب، ورسوم الاستكشاف البيانية. والمكوّن الذي يحتاج إلى حزمة
أخرى يستوردها عندما تستورده، لذا أضف الإضافات (extras) الخاصة بالمكوّنات التي
تستخدمها:

| الإضافة | ما تضيفه | لازمة لـ |
|---------|----------|----------|
| `config` | `pyyaml`، `python-dotenv` | `load_config`، `load_config_async`، `load_yaml` |
| `async` | `httpx`، `aiolimiter` | `AsyncArxivExtractor`، `AsyncPubMedExtractor`، `AsyncSemanticScholarExtractor`، `AsyncOpenAlexExtractor`، `build_async_client`، `AioLimiterRateLimiter` |
| `arxiv` | `beautifulsoup4`، `lxml` | `AsyncArxivExtractor`، الذي يحتاج أيضًا إلى `async` |
| `xml` | `lxml` | `JatsXmlParser` و`DocxParser` و`AsyncPubMedExtractor`، الذي يحتاج أيضًا إلى `async` |
| `html` | `beautifulsoup4` | `HtmlTextParser`، الذي يستخدمه `AsyncLLMEntityExtractor` افتراضيًا للنص الكامل الذي يبدأ بترميز |
| `processors` | `pandas`، `numpy` | كل خطوات `sci_etl_core.processors` عدا المدقّقات، ومصارف الجداول |
| `llm` | `openai`، `tiktoken` | `AsyncOpenAICompatibleClient`، والاقتطاع القائم على الرموز |
| `pdf` | `pdfplumber` | `PdfPlumberParser` |
| `sql` | `sqlalchemy` | `SqlTableSink`، الذي يحتاج أيضًا إلى `processors` |
| `viz` | `plotly` | `Plotly3DSink`، الذي يحتاج أيضًا إلى `processors` |
| `cluster` | `scikit-learn`، `numpy` | `ClusteringStep`، الذي يحتاج أيضًا إلى `processors` |
| `embeddings` | `numpy`، `openai` | `AsyncOpenAIEmbedder`، والمخازن المتجهية، و`AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `numpy`، `sentence-transformers` | `AsyncSentenceTransformerEmbedder` |
| `search` | لا شيء | لا شيء إضافي: لا تحتاج `sci_etl_core.search` إلا إلى المكتبة القياسية، فهذه الإضافة تسجّل فقط سبب تثبيت الحزمة |
| `full` | كل الحزم أعلاه عدا `sentence-transformers` | كل المكوّنات المضمّنة عدا التضمينات المحلية |
| `dev` | pytest وإضافاته، `hypothesis` | تشغيل مجموعة الاختبارات |
| `lint` | `ruff`، `mypy`، وملفات تعريف الأنواع | فحص الشيفرة المصدرية وأنواعها |
| `docs` | MkDocs، Material for MkDocs، mkdocstrings، mkdocs-click، mike، mkdocs-static-i18n، `ruff` | بناء موقع التوثيق هذا |

استيراد مكوّن تنقصه إضافته يرفع `ModuleNotFoundError` مع اسم الحزمة الواجب
تثبيتها.

!!! tip "تريد تشغيل خط معالجة فحسب؟"
    يثبّت `pip install sci-etl-cli` [الأمر `sci-etl`](../cli/index.md)، الذي
    يشغّل مشروع استخراج من arXiv انطلاقًا من ملف YAML دون شيفرة توصيل.
