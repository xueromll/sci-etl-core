# تحديد المعدل

يحدّ `AsyncETLPipeline(max_concurrency=...)` عدد السجلات التي تُعالَج في الوقت
نفسه. ولتحكم أدق، توفّر `sci_etl_core.rate_limiter` محدِّدات غير متزامنة:

- `SemaphoreRateLimiter`: حد للتزامن
- `AioLimiterRateLimiter`: دلو رموز (token bucket)؛ يحتاج إلى الإضافة `async`
- `NullRateLimiter`: بلا حد

تُعيد `build_rate_limiter(max_concurrency, max_rate, time_period)` دلو رموز عند
ضبط `max_rate`، وإشارة (semaphore) في غير ذلك. وتطابق معاملاتها
[قسم الإعداد](../getting-started/configuration.md) `full_text`.

## إعطاء محدِّد لمكوّن {#giving-a-limiter-to-a-component}

يقبل كل مستخرِج مضمَّن (`AsyncArxivExtractor` و`AsyncPubMedExtractor`
و`AsyncSemanticScholarExtractor` و`AsyncOpenAlexExtractor`)، وكذلك
`AsyncOpenAICompatibleClient` و`AsyncOpenAIEmbedder`، الوسيط `rate_limiter`.
ينتظر كل طلب HTTP، بما فيه إعادات المحاولة، خانة متاحة أولًا ويعيدها عند وصول
الاستجابة، فلا تبقى أي خانة محجوزة بينما ينتظر المكوّن إعادة المحاولة:

```python
from sci_etl_core import AsyncArxivExtractor
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncArxivExtractor(
    client=client,
    pdf_parser=PdfPlumberParser(),
    latex_parser=LatexTarballParser(),
    rate_limiter=build_rate_limiter(max_rate=1, time_period=3.0),
)
```

## حدود لكل مضيف {#limits-per-host}

يختار `HostRateLimiter` محدِّدًا وفق المضيف الذي يُرسَل إليه الطلب. ويشمل المضيف
نطاقاته الفرعية أيضًا، ما لم يكن لنطاق فرعي محدِّد خاص به، أما المضيفات التي لا
تطابق شيئًا فتستخدم `default`، الذي يعني عدم وجود حد إذا أغفلته. يتصل مستخرِج
arXiv بمضيفين، `export.arxiv.org` للقوائم و`arxiv.org` للنص الكامل، فيمكن أن
يحصل كل منهما على ميزانيته الخاصة:

```python
from sci_etl_core.rate_limiter import HostRateLimiter, SemaphoreRateLimiter, build_rate_limiter

arxiv_limits = HostRateLimiter(
    {
        "export.arxiv.org": build_rate_limiter(max_rate=1, time_period=3.0),
        "arxiv.org": SemaphoreRateLimiter(max_concurrency=4),
    }
)
```

## مشاركة حد بين المكوّنات {#sharing-a-limit-between-components}

مرّر المحدِّد نفسه إلى عدة مكوّنات لتتشارك ميزانية واحدة. فعميل المحادثة ومولّد
التضمينات اللذان يتصلان بالمزوّد نفسه يستهلكان الحصة نفسها:

```python
from sci_etl_core import AsyncOpenAICompatibleClient, AsyncOpenAIEmbedder
from sci_etl_core.rate_limiter import build_rate_limiter

provider_limit = build_rate_limiter(max_rate=50, time_period=60.0)
llm = AsyncOpenAICompatibleClient(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model=config.llm.model,
    rate_limiter=provider_limit,
)
embedder = AsyncOpenAIEmbedder(
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    model="text-embedding-3-small",
    rate_limiter=provider_limit,
)
```

ويمكن مشاركة `HostRateLimiter` بالطريقة نفسها، كأن تُستخدم نسخة واحدة تغطي
مضيفاتها كل خدمة يتصل بها التشغيل. وتطابقه العملاء المتوافقة مع OpenAI مع
`base_url` الخاص بها.
