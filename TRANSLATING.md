# Translating the Documentation

The documentation site is published in English, Russian, Spanish, Simplified
Chinese, and Modern Standard Arabic. English is the source, and every
translated page follows its English page. This guide names the owner of each
language, says how translations stay in sync, and lists the words to use.

## Ownership

| Language | Pages | Owner | Native-speaker reviewer |
|----------|-------|-------|-------------------------|
| Russian | `docs/**/*.ru.md` | [@xueromll](https://github.com/xueromll) | open |
| Spanish | `docs/**/*.es.md` | [@xueromll](https://github.com/xueromll) | open |
| Simplified Chinese | `docs/**/*.zh.md` | [@xueromll](https://github.com/xueromll) | open |
| Arabic (Modern Standard) | `docs/**/*.ar.md` | [@xueromll](https://github.com/xueromll) | open |

[`.github/CODEOWNERS`](.github/CODEOWNERS) assigns the same owners, so GitHub
asks the owner to review every pull request that touches their language.

The owner of a language:

- keeps every translated page in step with its English page, as
  [Keeping translations in sync](#keeping-translations-in-sync) describes;
- reviews and approves every change to the language's pages before it merges;
- decides how a new term is translated, and adds it to the
  [glossary](#glossary) before a page uses it.

A native-speaker reviewer checks that the wording reads naturally and that the
glossary uses the terms practitioners use. To review a language, open an issue
that names it, and the owner adds you to the table. Ownership of a language
moves when the current owner and the new owner agree; the table and
`CODEOWNERS` change in the same pull request.

## Keeping translations in sync

- **Same pull request.** A pull request that changes an English page under
  `docs/`, or a root file that a page under `docs/project/` renders
  (`CHANGELOG.md`, `MIGRATION.md`, `ROADMAP.md`, `CONTRIBUTING.md`,
  `SECURITY.md`, or `CODE_OF_CONDUCT.md`), updates the page's four
  translations too.
- **Can't write a language?** Say which in the pull request description. The
  owner of that language adds the translation before the pull request merges,
  so no translated page falls behind its English page on `master`.
- **New pages** ship with their four translations, and their menu title gets a
  `nav_translations` entry for each language in `mkdocs.yml`.
- **Glossary first.** A term the glossary lacks is added, in all four
  languages, in the pull request that first uses it.
- **English only.** This guide stays in English, since its glossary carries
  every language. The class and function descriptions on the API reference
  pages come from docstrings, and the CLI pages come from the sci-etl-cli
  repository, so both stay in English in every language.

## Writing a translated page

- **File.** `page.<lang>.md` beside `page.md`, where `<lang>` is `ru`, `es`,
  `zh`, or `ar`.
- **Structure.** The same headings in the same order and at the same levels,
  the same code blocks, the same links, and the same tables and admonitions.
  Only the words change.
- **Anchors.** Every heading below the page title ends with the anchor of its
  English heading, as in `## Ограничения по хостам {#limits-per-host}`. The
  anchor is the English heading in lowercase, with punctuation removed and
  spaces turned into hyphens; a heading repeated on one page gets `_1`, `_2`,
  and so on, as in the changelog. When unsure, read the heading's `id` in the
  built English page.
- **Links.** Point at the English file name, such as
  `../guide/sources.md#writing-an-extractor`. The build sends each language's
  link to the same page in that language.
- **Keep as they are:** code blocks, inline code, identifiers, file paths,
  commands, configuration keys, the log and error messages the library
  prints, prompts quoted in examples, product and project names, URLs, version
  numbers, dates, and commit-message examples. Comments in shell and Python
  examples may be translated.
- **Translate:** prose, table text, admonition titles, link text, and image
  alt text. Menu titles are translated in `nav_translations` in `mkdocs.yml`,
  not in the page.
- **Check.** `mkdocs build --strict` must pass. It fails on a link to an
  anchor that a translated heading lost.

## Style

| | Russian | Spanish | Simplified Chinese | Arabic |
|---|---------|---------|--------------------|--------|
| Register | neutral; instructions in the imperative, as in `Передайте` | `tú`, as in `Pasa` | `你`, not `您` | Modern Standard Arabic; instructions in the masculine singular imperative, as in `مرّر` |
| Quotation marks | «…» | "…" | “…” | "…" |
| Thousands | `9 999`, `10 000` | `9999`, `10 000` | `9,999` | `9,999` |
| Decimals | `0,35` | `0,35` | `0.35` | `0.35` |

- **Spanish.** "Pipeline" stays in English and is masculine: *el pipeline*.
- **Simplified Chinese.** Prose uses full-width punctuation (，。：；（）),
  code keeps half-width punctuation, and a space separates Chinese text from
  Latin words and inline code.
- **Arabic.** Use Western digits, the Arabic comma and semicolon (، ؛), and
  attach و directly to the inline code it joins, as in و`write`. A text
  diagram in a code block stays in English, because right-to-left text breaks
  its alignment; describe it in a paragraph below, as the architecture page
  does.

## Glossary

Use these terms. Each table is ordered as the documentation introduces the
ideas.

### Pipeline and runs

| English | Russian | Spanish | Simplified Chinese | Arabic |
|---------|---------|---------|--------------------|--------|
| library | библиотека | biblioteca | 库 | المكتبة |
| field of science | область науки | campo de la ciencia | 科学领域 | مجال من مجالات العلم |
| pipeline | конвейер | pipeline | 流水线 | خط المعالجة |
| run (noun) | запуск | ejecución | 运行 | التشغيل |
| paper | статья | artículo | 论文 | الورقة |
| record | запись | registro | 记录 | السجل |
| title / abstract / full text | заголовок / аннотация / полный текст | título / resumen / texto completo | 标题 / 摘要 / 全文 | العنوان / الملخص / النص الكامل |
| source | источник | fuente | 来源 | المصدر |
| extractor | экстрактор | extractor | 提取器 | المستخرِج |
| parser | парсер | analizador | 解析器 | المحلِّل |
| listing | выдача | listado | 列表 | القائمة |
| listing page | страница выдачи | página de listado | 列表页 | صفحة القائمة |
| cursor | курсор | cursor | 游标 | المؤشر |
| offset | смещение | desplazamiento | 偏移量 | الإزاحة |
| paging | листание | paginación | 分页 | التنقل بين الصفحات |
| result cap | лимит результатов | límite de resultados | 结果上限 | حد النتائج |
| truncated | усечённая | truncada | 截断 | مقتطعة |
| newest-first | «сначала новые» | de más recientes primero | 最新优先 | من الأحدث |
| relevance filter | фильтр релевантности | filtro de relevancia | 相关性过滤器 | مرشح الصلة |
| entity | сущность | entidad | 实体 | الكيان |
| entity extractor | экстрактор сущностей | extractor de entidades | 实体提取器 | مستخرِج الكيانات |
| exporter | экспортёр | exportador | 导出器 | المصدِّر |
| state manager | менеджер состояния | gestor de estado | 状态管理器 | مدير الحالة |
| processed / mark processed | обработанная / пометить как обработанную | procesado / marcar como procesado | 已处理 / 标记为已处理 | معالَج / تعليمه معالَجًا |
| settled | завершённая | resuelto | 已落定 | مُسوًّى |
| durable | надёжно сохранённая | duradero | 已持久化 | دائم |
| stalled page | застрявшая страница | página atascada | 停滞页 | صفحة متعثرة |
| quarantine / quarantined | карантин / в карантине | cuarentena / en cuarentena | 隔离 / 被隔离 | الحجر / محجور |
| attempt | попытка | intento | 尝试 | المحاولة |
| retry | повторная попытка | reintento | 重试 | إعادة المحاولة |
| backoff | отсрочка | espera exponencial | 退避 | التراجع |
| throttling | ограничение частоты | limitación de frecuencia | 限流 | الخنق |
| rate limiter | ограничитель частоты | limitador de frecuencia | 速率限制器 | محدِّد المعدل |
| flush the exporter | сбросить экспортёр | volcar el exportador | 刷新导出器 | تفريغ المصدِّر |
| flush the state | сбросить состояние на диск | volcar el estado | 写回状态 | حفظ الحالة |
| abort / aborted | прервать / прерванный | abortar / abortado | 中止 / 已中止 | إجهاض / مُجهَض |
| graceful shutdown | корректное завершение | apagado ordenado | 优雅关闭 | الإيقاف السلس |
| event loop | цикл событий | bucle de eventos | 事件循环 | حلقة الأحداث |
| blocking | блокирующий | bloqueante | 阻塞式 | متزامن |
| progress event | событие прогресса | evento de progreso | 进度事件 | حدث التقدم |
| run metrics | метрики запуска | métricas de ejecución | 运行指标 | مقاييس التشغيل |
| token usage | расход токенов | consumo de tokens | token 用量 | استهلاك الرموز |

### LLM, extraction, and claims

| English | Russian | Spanish | Simplified Chinese | Arabic |
|---------|---------|---------|--------------------|--------|
| LLM | LLM | LLM | LLM | النموذج اللغوي |
| prompt | промпт | prompt | 提示词 | الموجِّه |
| completion | ответ | respuesta | 回复 | الإكمال |
| response format | формат ответа | formato de respuesta | 响应格式 | تنسيق الاستجابة |
| structured output | структурированный вывод | salida estructurada | 结构化输出 | المخرجات المنظَّمة |
| response cache | кэш ответов | caché de respuestas | 响应缓存 | الذاكرة المؤقتة للاستجابات |
| cache hit / miss | попадание / промах | acierto / fallo de caché | 命中 / 未命中 | إصابة / إخفاق |
| schema | схема | esquema | 模式 | المخطط |
| typed entity | типизированная сущность | entidad tipada | 类型化实体 | الكيان المنمّط |
| validator | валидатор | validador | 校验器 | المدقّق |
| violation | нарушение | infracción | 违规项 | المخالفة |
| rejection | отклонение | rechazo | 拒绝 | الرفض |
| rejection store | хранилище отклонений | almacén de rechazos | 拒绝记录存储 | مخزن الرفض |
| claim | утверждение | afirmación | 论断 | الادعاء |
| provenance | происхождение | procedencia | 溯源 | المصدر |
| evidence sentence | предложение-доказательство | frase de evidencia | 证据句 | جملة الدليل |
| evidence span | фрагмент-доказательство | fragmento de evidencia | 证据片段 | مقطع الدليل |
| quote | цитата | cita | 引文 | الاقتباس |
| grounding | привязка к тексту | anclaje en el texto | 文本定位 | الإسناد إلى النص |
| stamp | штамп | sello | 标记 | الختم |

### Memory, search, and discovery

| English | Russian | Spanish | Simplified Chinese | Arabic |
|---------|---------|---------|--------------------|--------|
| embedding | эмбеддинг | embedding | 嵌入 | التضمين |
| embedder | эмбеддер | generador de embeddings | 嵌入器 | مولّد التضمينات |
| chunk | фрагмент | fragmento | 文本块 | المقطع |
| chunker | разбивщик | fragmentador | 分块器 | المقطِّع |
| passage | фрагмент | pasaje | 段落 | المقطع |
| vector store | векторное хранилище | almacén vectorial | 向量存储 | المخزن المتجهي |
| vector memory | векторная память | memoria vectorial | 向量记忆 | الذاكرة المتجهية |
| semantic memory | семантическая память | memoria semántica | 语义记忆 | الذاكرة الدلالية |
| memory ingest | загрузка в память | ingesta en memoria | 记忆摄取 | الاستيعاب في الذاكرة |
| memory ingestor | загрузчик | ingestor | 摄取器 | المستوعِب |
| memory fault | сбой памяти | fallo de memoria | 记忆故障 | عطل الذاكرة |
| store | хранилище | almacén | 存储 | المخزن |
| store owner | владелец хранилища | propietario del almacén | 存储的所有者 | مالك المخزن |
| text index | текстовый индекс | índice de texto | 文本索引 | الفهرس النصي |
| search (noun) | поиск | búsqueda | 检索 | البحث |
| query | запрос | consulta | 查询 | الاستعلام |
| term / phrase / prefix | термин / фраза / префикс | término / frase / prefijo | 词项 / 短语 / 前缀 | مصطلح / عبارة / بادئة |
| field scope | ограничение по полю | ámbito de campo | 字段限定 | تقييد الحقل |
| tokenizer | токенизатор | tokenizador | 分词器 | المجزّئ |
| hit | результат | resultado | 命中结果 | النتيجة |
| ranked search | ранжированный поиск | búsqueda por relevancia | 排序检索 | البحث المرتَّب |
| hybrid search | гибридный поиск | búsqueda híbrida | 混合检索 | البحث الهجين |
| lexical leg / semantic leg | лексическая ветвь / семантическая ветвь | rama léxica / rama semántica | 词法分支 / 语义分支 | الفرع المعجمي / الفرع الدلالي |
| rank fusion | слияние ранжирований | fusión de clasificaciones | 排名融合 | دمج الترتيب |
| candidate pool | пул кандидатов | grupo de candidatos | 候选池 | مجمع المرشحين |
| snippet | сниппет | extracto | 摘要片段 | المقتطف |
| highlight | подсветка | resaltado | 高亮 | الإبراز |
| filter | фильтр | filtro | 过滤器 | المرشح |
| facet | фасет | faceta | 分面 | الوجه |
| range | диапазон | rango | 范围 | النطاق |
| discovery graph | граф связанных статей | grafo de descubrimiento | 发现图 | رسم الاستكشاف البياني |
| node / edge | узел / ребро | nodo / arista | 节点 / 边 | العقدة / الحافة |
| edge source | источник рёбер | fuente de aristas | 边来源 | مصدر الحواف |
| community | сообщество | comunidad | 社区 | المجتمع |
| seed record | исходная запись | registro semilla | 种子记录 | سجل البذرة |
| read-model | модель чтения | modelo de lectura | 读模型 | نموذج القراءة |
| backfill | заполнение | relleno | 回填 | الملء |

### Post-processing

| English | Russian | Spanish | Simplified Chinese | Arabic |
|---------|---------|---------|--------------------|--------|
| post-processing | постобработка | posprocesamiento | 后处理 | المعالجة اللاحقة |
| processor | процессор | procesador | 处理器 | المعالِج |
| table sink | табличный приёмник | sumidero de tablas | 表格输出端 | مَصرِف الجداول |
| deduplication | дедупликация | deduplicación | 去重 | إزالة التكرار |
| normalizer | нормализатор | normalizador | 规范化器 | المُطبِّع |
| completeness | полнота | completitud | 完整性 | الاكتمال |
| clamp | зажимать | restringir | 截断 | الحصر |

### Releases and contributing

| English | Russian | Spanish | Simplified Chinese | Arabic |
|---------|---------|---------|--------------------|--------|
| release | выпуск | versión | 版本 | الإصدار |
| minor release | минорный выпуск | versión menor | 次版本 | الإصدار الفرعي |
| breaking change | ломающее изменение | cambio incompatible | 破坏性变更 | تغيير كاسر |
| deprecated | устаревший | obsoleto | 已弃用 | مهمل |
| provisional | предварительный | provisional | 临时性 | مؤقت |
| stable name | стабильное имя | nombre estable | 稳定名称 | اسم مستقر |
| consumer | потребитель | consumidor | 使用方 | المستهلك |
| extra | extra | extra | extra | الإضافة (extra) |
| base install | базовая установка | instalación base | 基础安装 | التثبيت الأساسي |
| test suite | набор тестов | batería de pruebas | 测试套件 | مجموعة الاختبارات |
| coverage | покрытие | cobertura | 覆盖率 | التغطية |
| issue | задача | incidencia | 议题 | المشكلة |
| pull request | pull request | pull request | pull request | طلب السحب |
| maintainer | сопровождающий | persona responsable del mantenimiento | 维护者 | القائم على الصيانة |

### Changelog headings

| English | Russian | Spanish | Simplified Chinese | Arabic |
|---------|---------|---------|--------------------|--------|
| Added | Добавлено | Añadido | 新增 | الإضافات |
| Changed | Изменено | Cambiado | 变更 | التغييرات |
| Deprecated | Устарело | Obsoleto | 弃用 | الإهمالات |
| Removed | Удалено | Eliminado | 移除 | المُزالات |
| Fixed | Исправлено | Corregido | 修复 | الإصلاحات |
| Security | Безопасность | Seguridad | 安全 | الأمان |
| **Breaking:** | **Ломающее изменение:** | **Incompatible:** | **破坏性变更：** | **تغيير كاسر:** |
