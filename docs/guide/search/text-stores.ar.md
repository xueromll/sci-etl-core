# مخازن النصوص

- **`InMemoryTextSearchStore(facet_keys=...)`** مناسب للاختبارات وعمليات التشغيل
  القصيرة. يطابق السجلات نفسها تمامًا التي يطابقها مخزن SQLite، ويحسب الدرجات
  بصيغة BM25 نفسها.
- **`AsyncSqliteFts5Store(path, facet_keys=..., weights=...)`** يحفظ الفهرس على
  القرص. يُخزَّن نص كل مقالة مرة واحدة، وكل عملية كتابة معاملة واحدة، وأي فشل في
  SQLite، بما في ذلك ملف ليس قاعدة بيانات، يرفع `SearchStoreError`. ويحدد
  `weights=BM25Weights(title=10.0, abstract=4.0, body=1.0)` وزن المطابقة في كل
  حقل؛ وهذه هي القيم الافتراضية.
- **FTS5 مطلوب.** يحتاج المخزن إلى بايثون بُنيت مكتبة SQLite فيه مع FTS5، وإلا
  رفع `SearchStoreError` عند إنشائه. تتحقق `fts5_available()` من ذلك مسبقًا؛
  أما `InMemoryTextSearchStore` فيعمل في كل مكان.
- **الصيانة صريحة.** تدمج `optimize()` مقاطع الفهرس. وتُعيد `integrity_check()`
  القيمة `False` عندما يختلف الفهرس عن المستندات المخزنة، كأن يكون الملف قد
  عُدِّل بأدوات أخرى، وتصلحه `rebuild_index()` من النص المخزن دون جلب أي شيء.
  والملف الذي أنشأه إصدار أحدث من المكتبة يرفع `SearchStoreError` بدلًا من أن
  يُستخدم.
- **المخازن المخصصة** ترث من `AsyncTextSearchStore`؛ راجع
  [إضافة مكوّن جديد](../../project/contributing.md#adding-a-new-component).
