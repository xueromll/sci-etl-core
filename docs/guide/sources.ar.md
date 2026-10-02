# المصادر المدعومة

لكل مصدر بروتوكوله ونموذج تقسيمه إلى صفحات ومخطط معرّفاته وتنسيقات نصوصه الكاملة،
ولذلك يحصل كل مصدر على `AsyncExtractor` خاص به بدلًا من مستخرِج واحد بمفاتيح تبديل لكل
مصدر.

| المصدر | المستخرِج | معرّف السجل | التقسيم إلى صفحات | النص الكامل |
|--------|-----------|-------------|-------------------|-------------|
| arXiv | `AsyncArxivExtractor` | معرّف arXiv مع الإصدار | إزاحات | مصدر LaTeX، ثم PDF، ثم الملخص |
| PubMed | `AsyncPubMedExtractor` | PMID | إزاحات، أول 9,999 نتيجة | JATS من PubMed Central إن كان للورقة معرّف PMC، وإلا فالملخص |
| Semantic Scholar | `AsyncSemanticScholarExtractor` | معرّف الورقة | إزاحات، أول 1,000 نتيجة | PDF مفتوح الوصول مع `pdf_parser`، وإلا فالملخص |
| OpenAlex | `AsyncOpenAlexExtractor` | معرّف العمل، مثل `W2741809807` | مؤشرات OpenAlex، بلا حد | PDF مفتوح الوصول مع `pdf_parser`، وإلا فالملخص |
| bioRxiv، ChemRxiv | غير مضمَّن | | | كيّف `AsyncArxivExtractor` |
| Crossref | غير مضمَّن | | | نفّذ `AsyncExtractor` خاصًا بك |

المستخرِج الذي يتنقل بين الصفحات بالإزاحة هو `OffsetListing`، وهو ما تحتاج إليه
تشغيلات `newest_first` و`run(start_index=)` بقيمة أكبر من 0. وعندما يتوقف المصدر عند حد
نتائجه الخاص، يعلّم مستخرِجه الصفحة التي تبلغ الحد بأنها `truncated`: فيكتمل التشغيل،
ويتصفح التشغيل التالي النتائج المتاحة من جديد بدلًا من التوقف عند الحد. وتُتخطى السجلات
المعالَجة حسب المعرّف، فلا تكلّف إعادة المسح هذه إلا طلبات قوائم، لا استدعاءات للنموذج
اللغوي. ولتجنبها، ضيّق الاستعلام، مثلًا بنطاق زمني. وفي
[دلالات التشغيل](run-semantics.md#capped-listings) التفاصيل.

تتشارك المستخرِجات المضمّنة سلوك إعادة المحاولة الموضح في [إعادة المحاولة](retries.md)
وتقبل `rate_limiter` ([تحديد المعدل](rate-limiting.md)). ويقبل كل منها أيضًا
`max_download_bytes`، الذي يحدّ كل متن استجابة بعد فك ترميزه: صفحة القائمة الكبيرة جدًا
ترفع `ExtractionError`، وتنزيل النص الكامل الكبير جدًا يُسجَّل ويُتجاوز. ويحدّ
`LatexTarballParser(max_tex_bytes=)` بالطريقة نفسها حجم TeX المفكوك من نسخة e-print
واحدة في arXiv. ويملأ كل منها `RawRecord.metadata` بالحقلين `authors` و`categories`،
وبالحقلين `published` و`year` حين يكون للمصدر تاريخ، فتعمل مرشحات البحث وأوجهه
بالطريقة نفسها عبر المصادر. وتخزّن المصادر الأخرى غير arXiv هناك أيضًا `pdf_url` أو
`pmcid`، اللذين تقرؤهما `fetch_full_text`.

## PubMed {#pubmed}

```python
from sci_etl_core import AsyncPubMedExtractor
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncPubMedExtractor(
    client,
    api_key=ncbi_api_key,
    tool="my-project",
    email="you@example.org",
    rate_limiter=build_rate_limiter(max_rate=9, time_period=1.0),
)
await pipeline.run("dark matter[tiab] AND 2020:2026[dp]", total_limit=200, newest_first=True)
```

يستخدم الاستعلام صياغة البحث في PubMed. والنتائج مرتبة من الأحدث (`sort="pub_date"`)،
فيناسبها `newest_first=True`. وتكلّف كل صفحة من القائمة طلبين، وتسمح NCBI بـ 3 طلبات
في الثانية دون مفتاح واجهة برمجية و10 مع مفتاح، فاقرأ المفتاح من البيئة واضبط محدِّدًا دون
ذلك. ولا يتصفح E-utilities إلا أول 9,999 نتيجة من البحث، حتى عبر خادم السجل الخاص به،
فتُعلَّم الصفحة التي تبلغها بأنها `truncated`. وتضيف البيانات الوصفية `journal`، و`doi`
و`pmcid` عند معرفتهما؛ و`categories` هي عناوين MeSH.

## Semantic Scholar {#semantic-scholar}

```python
from sci_etl_core import AsyncSemanticScholarExtractor
from sci_etl_core.parsers import PdfPlumberParser
from sci_etl_core.rate_limiter import build_rate_limiter

extractor = AsyncSemanticScholarExtractor(
    client,
    PdfPlumberParser(),
    api_key=semantic_scholar_key,
    year="2020-",
    fields_of_study="Physics",
    rate_limiter=build_rate_limiter(max_rate=1, time_period=1.0),
)
```

لا يُعيد البحث حسب الصلة إلا أول 1,000 نتيجة، ولا يرتبها حسب التاريخ، فشغّله دون
`newest_first`؛ وتُعلَّم الصفحة التي تبلغ النتيجة رقم 1,000 بأنها `truncated`. وتضيف
البيانات الوصفية `venue`، و`doi` و`arxiv_id` و`pmid` عند معرفتها.

## OpenAlex {#openalex}

```python
from sci_etl_core import AsyncOpenAlexExtractor

extractor = AsyncOpenAlexExtractor(
    client,
    filter="type:article,from_publication_date:2020-01-01",
    mailto="you@example.org",
)
await pipeline.run("ultra-diffuse galaxies", total_limit=500)
```

النتائج مرتبة من الأحدث افتراضيًا (`sort="publication_date:desc"`). ويستخدم التقسيم إلى
صفحات مؤشرات OpenAlex، فلا تقتصر القائمة على أول 10,000 نتيجة، لكن المستخرِج ليس
`OffsetListing` ولا يدعم تشغيلات `newest_first`. وعندما يبلغ التشغيل نهاية القائمة، يبدأ
التشغيل التالي من الصفحة الأولى من جديد ويتخطى الأعمال المعالَجة حسب المعرّف. والمؤشر الذي
يرفضه OpenAlex يعيد بدء القائمة مرة واحدة. ويضمّك `mailto` إلى "المجمع المهذب" (polite
pool) في OpenAlex. وتُعاد بناء الملخصات من الفهرس المقلوب في OpenAlex. وتضيف البيانات
الوصفية `doi` و`venue` و`references`، وهي معرّفات الأعمال التي تستشهد بها الورقة.

## تنسيقات المستندات {#document-formats}

إلى جانب محلِّلات PDF وLaTeX وHTML التي تستخدمها المستخرِجات، يقرأ محلِّلان تنسيقات قد
تحصل عليها من مصادر أخرى:

- **`DocxParser`** يقرأ ملفات Word بصيغة `.docx` بالمكتبة القياسية و`lxml`: الفقرات
  بالترتيب، والجداول صفوفًا مفصولة بعلامات جدولة، ومع `include_notes=True` الحواشي
  السفلية والختامية.
- **`JatsXmlParser`** يقرأ JATS XML، وهو تنسيق PubMed Central وكثير من الناشرين. تُعيد
  `extract_text` العنوان والملخص والمتن دون قائمة المراجع، وتُعيد `parse_article`
  كائن `JatsArticle` يتضمن الأقسام والمؤلفين والكلمات المفتاحية والمجلة وتاريخ النشر
  والمعرّفات والمراجع.

```python
from sci_etl_core.parsers import JatsXmlParser

article = JatsXmlParser().parse_article(xml_bytes)
print(article.title, article.doi, [section.title for section in article.sections])
```

يحلل كلاهما XML دون تحليل الكيانات ودون جلب ملفات DTD، ويرفعان `ParsingError` للبايتات
التي يعجزان عن قراءتها.

## كتابة مستخرِج {#writing-an-extractor}

يعمل خط المعالجة مع أي صنف ينفّذ هذا العقد:

```python
from sci_etl_core import AsyncExtractor, ListingPage
from sci_etl_core.models import RawRecord


class MySourceExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage: ...

    async def fetch_full_text(self, record: RawRecord) -> str: ...
```

- **`fetch_page`** تجلب صفحة واحدة وتحللها. `cursor=None` هو الصفحة الأولى؛ وأي مؤشر
  آخر هو `next_cursor` أعادته صفحة سابقة، ربما في تشغيل سابق. وتُعيد `ListingPage` تضم
  كل سجل استطاعت قراءته، وعدد المدخلات في الصفحة بما فيها ما تعذّرت قراءته، والمؤشر
  التالي، أو `None` في الصفحة الأخيرة. ويتخطى خط المعالجة السجلات المعالَجة بنفسه.
  والمصدر الذي توقف عند حد نتائجه الخاص يُعيد `truncated=True`.
- الأخطاء: إن تعذّر الوصول إلى المصدر فارفع `UpstreamError` بدلًا من إعادة صفحة فارغة؛
  وإن رفض الطلب صراحة فارفع `ExtractionError`؛ وإن تعذّرت قراءة الحمولة فارفع
  `MalformedResponseError`. وكل منها يُجهض التشغيل. وإن لم يعد المصدر يقبل مؤشرًا فارفع
  `StaleCursorError`، فيعيد التشغيل بدء القائمة من الصفحة الأولى مرة واحدة.
- **`cursor_for_offset`** خاصة بالمصدر الذي يتنقل بين الصفحات بالإزاحة. وهي تجعل المستخرِج
  `OffsetListing`؛ أغفلها حين تكون المؤشرات رموزًا مبهمة.
- **`fetch_full_text`** تُعيد أفضل نص متاح للسجل.

العقد الكامل لكل نوع من المكوّنات مسرود في
[إضافة مكوّن جديد](../project/contributing.md#adding-a-new-component)، ويوثّق
[مرجع واجهة المستخرِجات البرمجية](../reference/extractors.md) الأصناف الأساسية.
