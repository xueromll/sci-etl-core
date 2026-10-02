# الإعداد

تُحمَّل الإعدادات من ملف YAML، واختياريًا من ملف `.env`، إلى نماذج Pydantic. ويحتاج
التحميل إلى الإضافة `config`:

```python
from pathlib import Path

from sci_etl_core import BaseAppConfig, load_config

config = load_config(BaseAppConfig, Path("config.yaml"), Path(".env"))
print(config.llm.model, config.pipeline.total_limit)
```

```yaml title="config.yaml"
llm:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  timeout: 120
http:
  user_agent: "my-project/1.0 (mailto:you@example.org)"
  max_retries: 3
  timeout: 25
full_text:
  max_concurrency: 4
pipeline:
  search_query: "all:galaxy"
  total_limit: 100
  page_size: 100
  search_delay: 3.0
  sleep_between: 5.0
  max_concurrency: 6
  newest_first: true
search:
  bm25: {title: 10, abstract: 4, body: 1}
  fusion: {k: 60}
  hybrid: {candidate_pool: 100, chunk_pool_factor: 5}
  graph: {depth: 2, fanout: 8, min_weight: 0.35}
```

| القسم | النموذج | الحقول (القيم الافتراضية) | ما يبنيه |
|-------|---------|---------------------------|----------|
| `llm` | `LLMConfig` | `api_key`، `base_url` (`https://api.openai.com/v1`)، `model` (`gpt-4o-mini`)، `timeout` (120)، `structured_output` (false) | `AsyncOpenAICompatibleClient.from_config` |
| `http` | `HttpConfig` | `user_agent` (`sci-etl-core/<installed version>`)، `max_retries` (3)، `backoff_factor` (2.0)، `timeout` (25) | `build_client()`، `AsyncArxivExtractor.from_config` |
| `full_text` | `RateLimitConfig` | `max_concurrency` (4)، `max_rate` (غير مضبوط)، `time_period` (1.0) | `build_limiter()`، `AsyncArxivExtractor.from_config` |
| `pipeline` | `PipelineConfig` | `search_query` (`""`)، `total_limit` (100)، `page_size` (100)، `search_delay` (3.0)، `sleep_between` (5.0)، `max_concurrency` (6)، `newest_first` (false) | `AsyncETLPipeline.from_config`، `run_arguments()`، `AsyncArxivExtractor.from_config` |
| `search` | `SearchConfig` | `bm25`، `fusion`، `hybrid`، `graph`، بالقيم الافتراضية لأصناف البيانات التي تبنيها | `bm25.to_weights()`، `fusion.to_params()`، `hybrid.to_params()`، `graph.to_params()` |

## بناء المكوّنات من الإعداد {#building-components-from-the-config}

يبني كل قسم المكوّنات التي يضبطها، أو يُمرَّر إليها. والقيم التي تمررها بنفسك تتقدم على
الإعداد:

```python
from sci_etl_core import AsyncArxivExtractor, AsyncETLPipeline, AsyncOpenAICompatibleClient
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

extractor = AsyncArxivExtractor.from_config(
    config.http,
    config.pipeline,
    client=config.http.build_client(),
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    full_text=config.full_text,
)
llm = AsyncOpenAICompatibleClient.from_config(config.llm)
pipeline = AsyncETLPipeline.from_config(
    config.pipeline,
    extractor=extractor,
    relevance_filter=relevance_filter,
    entity_extractor=entity_extractor,
    exporter=exporter,
    state_manager=state_manager,
)
await pipeline.run(**config.pipeline.run_arguments())
```

يأخذ `AsyncArxivExtractor.from_config` القيمتين `max_retries` و`backoff_factor` من
`http`، و`search_delay` من `pipeline`، و`rate_limiter` الخاص به من `full_text`. وإن
أغفلت `full_text` فلن يكون للمستخرِج محدِّد معدل، فيُنزّل خط معالجة قيمة
`max_concurrency` فيه 6 ست أوراق من arxiv.org في آن واحد. ويأخذ
`AsyncOpenAICompatibleClient` القيمة `api_key` (كائن `SecretStr` المحمَّل كما هو)
و`base_url` و`model` و`structured_output`، و`timeout` بوصفها `default_timeout`. لا
تضبط `structured_output: true` إلا لنقطة نهاية تقبل تنسيق الاستجابة `json_schema`، مثل
نقطة OpenAI؛ أما نقطة DeepSeek فلا تقبله. ويقبل كلاهما أي وسيط آخر للمُنشئ، مثل
`rate_limiter`، بالاسم. ليس لمستخرِجات PubMed وSemantic Scholar وOpenAlex دالة
`from_config`؛ مرّر `config.http.max_retries` و`config.http.backoff_factor` إلى
مُنشئاتها بنفسك. ويأخذ خط المعالجة `max_concurrency`، وتُعيد `run_arguments()` القيم
`query` و`page_size` و`total_limit` و`sleep_between` و`newest_first` لـ `run()`؛ أضف
`max_attempts` أو `start_index` بنفسك عند الحاجة. وتعمل `ETLPipeline.from_config`
بالطريقة نفسها.

يبني القسم search أصناف بيانات المعاملات الخاصة بـ
[البحث المحلي](../guide/search/index.md):

```python
from sci_etl_core.search import AsyncHybridSearcher, AsyncSqliteFts5Store

store = AsyncSqliteFts5Store("search.db", weights=config.search.bm25.to_weights())
searcher = AsyncHybridSearcher(
    store,
    finder,
    fusion=config.search.fusion.to_params(),
    params=config.search.hybrid.to_params(),
)
```

## الأقسام الصارمة {#strict-sections}

يرفض كل قسم تعرّفه المكتبة أي مفتاح لا يعلنه، فيفشل الخطأ الإملائي بوضوح بدلًا من أن
يُتجاهل. ويسمّي `ConfigurationError` المفتاح:

```text
Invalid configuration in config.yaml:
  search.bm25.titel: Extra inputs are not permitted
```

والمفتاحان `pipeline.max_records` و`pipeline.max_workers`، اللذان أُعيدت تسميتهما في
0.4، يُرفضان بالطريقة نفسها منذ 0.5؛ استخدم `total_limit` و`max_concurrency`. والتطبيق
الذي لا يزال مضطرًا إلى تحميل ملف فيه مفاتيح مجهولة داخل أقسام المكتبة يضبط
`strict_sections = False` في صنف إعداده. وعندئذ يُحذف كل مفتاح مجهول مع تحذير
`UserWarning` يسمّيه:

```python
from sci_etl_core import BaseAppConfig


class MyConfig(BaseAppConfig):
    strict_sections = False
```

الأقسام العليا التي يضيفها تطبيقك تُحفظ في الحالتين، ونوع القسم الذي تعرّفه بنفسك
يُتحقق منه وفق ما يقوله `model_config` الخاص به.

## التفاصيل {#details}

- **مفتاح الواجهة البرمجية.** يأتي المفتاح من متغير البيئة `LLM_API_KEY` (اختر غيره
  بـ `api_key_env_var=`). ولا يُقرأ ملف `.env` إلى البيئة إلا عندما تطلب ذلك: مرّر
  مساره بوصفه `env_path`، أو مرّر `load_env=True` لاستخدام أول `.env` يُعثر عليه صعودًا
  من دليل العمل الحالي. ودون أيٍّ منهما لا تقرأ `load_config` ملف `.env` أبدًا، فلا
  يغيّر استيراد المكتبة وإعدادها أي متغير بيئة. ويُخزَّن المفتاح بوصفه `SecretStr` من
  Pydantic، فلا يظهر في التمثيلات النصية ولا في السجلات. والمتغيرات المضبوطة مسبقًا في
  البيئة تتقدم على `.env`؛ انسخ `.env.example` للبدء.
- **البيئة تتقدم على YAML.** عندما يكون المتغير مضبوطًا، فإنه يتجاوز أي `llm.api_key`
  في ملف YAML، الذي لا يُستخدم إلا احتياطًا. ومع ذلك أبقِ المفاتيح خارج ملفات الإعداد.
- **إعدادات خاصة بالمشروع.** يقبل `BaseAppConfig` مفاتيح عليا إضافية، أو يمكنك الوراثة
  منه. أما المفاتيح داخل أقسام المكتبة نفسها فيجب أن تكون مما تعلنه تلك الأقسام؛ راجع
  [الأقسام الصارمة](#strict-sections).
- **التحميل غير المتزامن.** تأخذ `load_config_async` الوسائط نفسها.
- **الأخطاء.** ملف YAML المفقود أو غير القابل للتحليل، والملف الذي لا يكون مستواه
  الأعلى ربطًا (mapping)، وفشل التحقق، كلها ترفع `ConfigurationError`. ويفحص التحقق
  النطاقات أيضًا: يجب ألا تقل الأعداد مثل `max_concurrency` و`page_size` و`max_retries`
  عن 1، وأن تكون المهل و`time_period` موجبة، وألا تكون فترات الانتظار و`total_limit`
  سالبة، وأن تكون أوزان BM25 منتهية وغير سالبة، وأن تكون `graph.min_weight` منتهية. ولا
  تُفحص `fusion.weights` إلا عندما تبني `fusion.to_params()` المعاملات، فترفع
  `ValueError` للوزن السالب أو غير المنتهي. وتسرد رسالة التحقق كل مفتاح فاشل وسببه في
  سطر مستقل لكنها لا تذكر القيمة أبدًا، فلا يمكن لمفتاح واجهة برمجية أن يصل عبرها إلى
  سجل. وتطبّق `validate_config(config_cls, raw, source)` الفحوص نفسها على إعدادات
  حُمّلت بطريقة أخرى.
