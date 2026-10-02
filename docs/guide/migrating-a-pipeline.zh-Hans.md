# 迁移流水线

本指南把一条现有的科研流水线迁移到 `sci-etl-core` 上，并以一次真实的迁移作为完整示例：
[udg-catalogue](https://github.com/xueromll/udg-catalogue)，它借助 LLM 从 arXiv 论文中
构建超弥散星系（UDG）星表。

每段“迁移前”代码都取自迁移前的 udg-catalogue。第 1 到第 9 步中的每段“迁移后”代码都取自
基于 sci-etl-core 0.2 迁移后的项目，位于
[提交 `8cd9471`](https://github.com/xueromll/udg-catalogue/tree/8cd94711b864212a8fa0d55d60f51e500cf42ec3)。
其中一些 0.2 的调用此后已被改名或移除。[最终效果](#where-youll-end-up)展示了基于 0.6 的
项目，[升级项目](#upgrading-the-project)展示了该项目
[`main` 分支](https://github.com/xueromll/udg-catalogue/tree/main)上的代码在迁移到 0.4、
0.5 和 0.6 时如何变化。[迁移指南](../project/migration.md)按版本列出了所有变更。示例的
学科是天文学，但各个步骤并不依赖于它：把提示词、字段和领域规则换成你自己的即可。

- [迁移前的项目](#the-project-before)
- [最终效果](#where-youll-end-up)
- [把你的流水线对应到本库](#map-your-pipeline-onto-the-library)
- [第 1 步：安装并链接本库](#step-1-install-and-link-the-library)
- [第 2 步：配置与密钥](#step-2-configuration-and-secrets)
- [第 3 步：来源与全文](#step-3-source-and-full-text)
- [第 4 步：LLM 步骤](#step-4-the-llm-steps)
- [第 5 步：把领域规则做成插件](#step-5-domain-rules-as-plug-ins)
- [第 6 步：导出与状态](#step-6-export-and-state)
- [第 7 步：后处理](#step-7-post-processing)
- [第 8 步：先核对结果一致，再改变行为](#step-8-check-parity-before-changing-behavior)
- [第 9 步：删除旧代码](#step-9-delete-the-old-code)
- [升级项目](#upgrading-the-project)
- [迁移中发现的问题](#what-the-migration-uncovered)
- [将其应用到你的领域](#adapting-this-to-your-field)

---

## 迁移前的项目 {#the-project-before}

udg-catalogue 在 arXiv 中检索 `cat:astro-ph.GA AND abs:ultra-diffuse`。对每篇论文，它会
询问 LLM 摘要是否报告了真实的观测，下载 LaTeX 源文件或 PDF，请 LLM 以 JSON 形式提取每个
星系，并把这些星系合并到一个 CSV 中。随后的后处理步骤会去除重复项、为完整性打分、分配星座
和三维聚类，并写出排好序的星表，供 Streamlit 仪表盘使用。

ETL 机制位于项目根目录下的扁平模块中：

| 模块 | 行数 | 职责 |
|------|------|------|
| `arxiv_client.py` | 198 | arXiv 检索与 Atom 解析、LaTeX 和 PDF 下载、表格提取、参考文献裁剪、两次 LLM 调用 |
| `data_processor.py` | 314 | 已处理 id 文件、星系校验、CSV upsert、去重、完整性、星座、聚类、质量标记 |
| `main.py` | 94 | 基于 `ThreadPoolExecutor` 的分页循环 |
| `config.py`、`logger.py`、`incremental.py` | 97 | 把 YAML 读入模块常量、日志设置、续跑偏移量 |

`main.py` 中的编排循环如下：

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

## 最终效果 {#where-youll-end-up}

迁移之后，整个摄取部分只剩几个把本库组件组装在一起的函数。下面是基于 sci-etl-core 0.6 的
`udg_catalogue/pipeline.py`，只保留了摄取流水线，并去掉了记录进度的包装层：

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

`build_pipeline` 以参数形式接收 HTTP 客户端和 LLM 客户端，因此项目的测试可以传入一个提供
虚假 Atom 订阅源和 e-print 的 `httpx.MockTransport`，再加上一个按脚本应答的
`AsyncLLMClient`，从而离线运行真实的流水线。

`main.py` 精简为加载配置、运行摄取和生成输出：

```python
config = load_catalogue_config(arguments.config)
log = configure_run_logging(config.paths.log_file)
processed = asyncio.run(run_ingestion(config, log, start_index, ShutdownSignal()))
catalogue = build_sorted_catalogue(config, log.info, replace=arguments.replace_catalogue)
write_manifest(config, log.info)
```

留在项目中的，是只有天文学家才能写的部分：提示词、星系命名和校验规则、天球位置匹配、聚类
所用的特征，以及仪表盘。

## 把你的流水线对应到本库 {#map-your-pipeline-onto-the-library}

首先把旧流水线中的每个函数归入三类之一：由本库组件替代、由本库组件加一个小插件替代，或者
保留。

| 迁移前（udg-catalogue） | 迁移后 | 仍需自己编写的部分 |
|-------------------------|--------|--------------------|
| `search_arxiv`、`parse_arxiv_xml` | `AsyncArxivExtractor` | 无 |
| `fetch_paper_text`、`extract_tables_from_pdf`、`trim_references` | 搭配 `LatexTarballParser` 和 `PdfPlumberParser` 的 `AsyncArxivExtractor` | 无 |
| 带 `Retry` 的 `requests` 会话 | `build_async_client` | 无 |
| `is_paper_relevant` | `AsyncLLMRelevanceFilter` | 提示词 |
| `extract_udg_data` | `AsyncLLMEntityExtractor(result_key="galaxies")` | 提示词 |
| 指向 DeepSeek 的 OpenAI 客户端 | `AsyncOpenAICompatibleClient` | 基础 URL 和模型 |
| `upsert_to_csv` | `AsyncCsvExporter`，然后在后处理中使用 `DeduplicationStep` | 列清单 |
| `load_processed_ids`、`save_processed_id`、`incremental.py` | `AsyncFileStateManager` | 文件路径 |
| `main.py` 中的循环 | `AsyncETLPipeline` | 上面的组装代码 |
| `logger.py` | 标准 `logging` 模块 | 运行日志的处理器 |
| `config.py` | `BaseAppConfig` 子类和 `load_config` | 项目设置 |
| `universal_normalize_name` | `KeyNormalizer` 子类 | 名称匹配规则 |
| `is_valid_galaxy` | 传给 `AsyncLLMEntityExtractor(validator=)` 的 `RecordValidator` | 字段规则 |
| `clean_duplicates` | `NormalizationStep` 和 `DeduplicationStep` | 用于天球位置的 `NeighborMatcher` |
| `calculate_completeness`、`assign_quality_flag` | `CompletenessStep`、`QualityFlagStep` | 字段清单 |
| `assign_3d_clusters` | `ClusteringStep` | 用于三维位置的 `FeatureExtractor` |
| `assign_constellations`、绘图、仪表盘 | 保留 | 领域代码，适合时写成 `Processor` |

该表列出的是 sci-etl-core 0.6 的组件。第 1 到第 9 步展示的是 udg-catalogue 当时使用的 0.2
组件，例如带 upsert 功能的 CSV 导出器和带校验功能的提取器包装层，它们在后续版本中已被替代。

## 第 1 步：安装并链接本库 {#step-1-install-and-link-the-library}

迁移期间你会同时修改两个代码库，因此请以可编辑模式把本库安装到项目的环境中。udg-catalogue
与它的 sci-etl-core 克隆相隔两级目录：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "../../sci-etl-core[async,llm,pdf,cluster]"
python -c "import sci_etl_core; print(sci_etl_core.__file__)"
```

在 Windows 上用 `.venv\Scripts\activate` 激活环境。最后一条命令应当打印出克隆目录中 `src`
文件夹内的路径。请为你使用的组件选择 extra：udg-catalogue 需要 `async`（用于 arXiv 提取器
和 CSV 导出器）、`llm`（用于 OpenAI 兼容客户端）、`pdf`（用于 `PdfPlumberParser`）以及
`cluster`（用于 `ClusteringStep`）。

可编辑安装会记录克隆目录的绝对路径。如果移动或重命名本库的文件夹，`import sci_etl_core` 会
失败，直到你重新安装；udg-catalogue 的工作区被移入同步的 OneDrive 文件夹时，恰好发生了这种
情况。

部署环境看不到相邻的克隆目录，而 pip 也无法在同一次依赖解析中从两个来源安装同一个包。因此，
udg-catalogue 把锁定版本的第三方包放在 `requirements-app.txt` 中，并通过两个很薄的文件选择
本库的来源。本地开发使用 `requirements-local.txt`：

```text
-r requirements-app.txt
-e ../../sci-etl-core[async,llm,pdf,cluster]
```

Docker、CI 和新用户使用 `requirements.txt`，它从 PyPI 安装已发布的版本：

```text
-r requirements-app.txt
sci-etl-core[async,llm,pdf,cluster]>=0.2.0,<0.3
```

请锁定一个版本范围而不是某个确切版本，这样修复版本无需修改项目即可到达；在用你的测试验证过
新的次版本之后，再有意识地提高上限。本库发布到 PyPI 之前，udg-catalogue 会提交一个用
`pip wheel --no-deps -w vendor path/to/sci-etl-core` 构建的 wheel，并从 `vendor/` 安装它；
对于无法访问 PyPI 的构建，这种做法仍然可行。

## 第 2 步：配置与密钥 {#step-2-configuration-and-secrets}

**迁移前**（`config.py`）：导入模块时，YAML 被读入模块级常量。

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

**迁移后**：`config.yaml` 使用本库的部分（`llm`、`http`、`pipeline`）以及项目自己的部分
（`paths`、`clustering`、`deduplication`）：

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

`udg_catalogue/config.py` 继承本库的模型：

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

这里有三个值得借鉴的做法：

- **保留密钥变量的名称。** `api_key_env_var="DEEPSEEK_API_KEY"` 意味着现有的 `.env` 文件和
  Docker Compose 文件无需修改即可继续使用。密钥以 `SecretStr` 保存，因此永远不会出现在 repr
  或日志中。
- **通过继承扩展配置部分。** `CataloguePipelineConfig` 添加了 `page_size` 和
  `search_delay`，同时保留了本库读取的所有字段。
- **相对于配置文件解析路径。** 显式传入配置文件旁边的 `.env`，并把相对路径锚定到配置文件所在
  的文件夹，意味着无论从哪个目录启动，流水线的行为都相同。旧代码把大多数路径相对于脚本文件夹
  解析，却把 `pipeline_meta.json` 和 `analysis/` 相对于工作目录解析。

配置值不会自动生效：要像 `build_pipeline` 那样，把它们传给构造函数和 `run()`。

## 第 3 步：来源与全文 {#step-3-source-and-full-text}

**迁移前**（`arxiv_client.py`，有删节）：

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

**迁移后**：

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

行为上的变化：

- **检索失败是错误，而不是数据的结尾。** `search_arxiv` 过去返回 `None`，`main.py` 中的循环
  把它当作“没有更多论文”，并继续报告成功。旧日志显示有 9 次运行就是这样停止的。现在
  `AsyncETLPipeline.run()` 会抛出 `PipelineAborted`，`main.py` 以状态码 1 退出。
- **重试的等待时间比默认值更长。** 提取器在两次尝试之间等待 `backoff_factor ** attempt` 秒，
  因此默认因子 2 会先等 1 秒、再等 2 秒。arXiv 以 `429` 限流的时间比这更长，而旧代码在收到
  429 后会等 20 秒，所以 udg-catalogue 设置了 `backoff_factor: 5.0` 和 `max_retries: 4`
  （分别等待 1、5 和 25 秒）。
- **重新启用了 TLS 校验。** 旧的 e-print 下载使用了 `verify=False`。
- **更多投稿能得到 LaTeX。** 单个 gzip 压缩的 `.tex` 文件会被读取，而不会退回到 PDF；多文件
  源码会按 `\input` 的顺序拼装。
- **其他一切保持不变。** 参考文献裁剪的模式仍是同样的七个表达式，PDF 解析器仍在同样的
  `--- EXTRACTED TABLES ---` 标记下追加表格。对于三篇近期论文，新旧代码返回的文本逐字节相同。

## 第 4 步：LLM 步骤 {#step-4-the-llm-steps}

**迁移前**（`arxiv_client.py`，有删节）：

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

**迁移后**（与 `run_ingestion` 和 `build_pipeline` 中相同的调用，提取到变量中）：

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

提示词被逐字搬到了 `udg_catalogue/prompts.py`。它们本来就提到了 JSON（JSON 模式要求如此），
提取提示词也本来就要求返回 `{"galaxies": [...]}`，因此 `result_key="galaxies"` 正好读取这种
形式，提示词无需修改。120,000 字符的上限、去除 HTML 以及温度为 0，也都是本库的默认值。

行为上的变化：

- **相关性判断仍然在出错时放行。** 与以前一样，调用失败时论文会被放行，超时仍为 20 秒。一个
  区别是：没有明确结论的回复现在也会放行论文，而旧代码把缺少 `relevant` 键视为 `False`。传入
  `default_on_error=False` 可以改为拦下这类论文；自 0.5.1 起，它们会在下一次运行时重试。
- **提取失败会被重试。** DeepSeek 出错时 `extract_udg_data` 返回 `[]`，于是论文在什么都没
  提取出来的情况下被标记为已处理；旧日志显示有 8 篇这样的论文，它们永远不会再被重新访问。
  `AsyncLLMEntityExtractor` 会抛出 `LLMError`，流水线让论文保持未标记状态，下一次运行会再次
  尝试。

## 第 5 步：把领域规则做成插件 {#step-5-domain-rules-as-plug-ins}

判断什么算作同一个星系、什么算作真实星系的规则属于科学，它们留在项目中。本库为它们提供了
接入的位置。

### 名称匹配：`KeyNormalizer` {#name-matching-a-keynormalizer}

**迁移前**（`data_processor.py`）：

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

先把这样的函数**原样**移植为 `KeyNormalizer` 子类，这样第 8 步的一致性核对比较的只是底层衔接
部分，别无其他。udg-catalogue 正是这样做的。

后来发现这个函数会把不同的星系合并在一起（参见[迁移中发现的问题](#what-the-migration-uncovered)），
因此在确认结果一致之后就替换了它。**迁移后**（`udg_catalogue/naming.py`）：

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

`DF 44`、`DF044` 和 `Dragonfly 44` 仍然共享键 `df44`，而 `KDG 44`、`NGC 1052-DF2` 和
`NGC 1052-DF4` 现在各自保留自己的键。把缺失值检查委托给 `DefaultKeyNormalizer`，意味着
`None`、`NaN` 和非标量值都会按本库每个组件所期望的方式处理。CSV 导出器和后处理去重都使用
`GalaxyNameNormalizer`，因此这两个阶段对“哪些是同一个天体”的判断始终一致。

### 校验：`RecordValidator` 与包装层 {#validation-recordvalidators-and-a-wrapper}

**迁移前**（`data_processor.py`）：校验逻辑埋在 `upsert_to_csv` 内部。

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

**迁移后**（`udg_catalogue/validation.py`）：本库的校验器覆盖关键词规则和范围规则，其余部分
由一个小类负责。

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

`AsyncETLPipeline` 本身不调用校验器，因此由一个很薄的 `AsyncEntityExtractor` 在提取和导出
之间应用它们，并记录被丢弃的内容：

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

在用 `KeywordExclusionValidator` 替代旧的正则表达式之前，请用你现有的数据对比两者。在
udg-catalogue 中，两者对全部 1,285 个已存储的名称以及 `TNG50-1`、`illustris_galaxy_1` 和
`Firefly 7` 等边界情况的判断都一致。

## 第 6 步：导出与状态 {#step-6-export-and-state}

**迁移前**（`data_processor.py` 和 `incremental.py`，有删节）：每个工作线程都会读取整个
CSV、修改它再写回，六个线程之间没有任何锁。

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

**迁移后**（`build_catalogue_exporter` 和 `build_pipeline` 中的状态管理器，代入了
`udg_catalogue/config.py` 中的常量并写出了默认路径）：

```python
exporter = AsyncCsvUpsertExporter(
    key_column="galaxy_name",
    value_columns=["ra", "dec", "distance_mpc", "effective_radius_kpc", "stellar_mass_solar", "dark_matter_fraction"],
    normalizer=GalaxyNameNormalizer(),
    numeric_clip={"dark_matter_fraction": (0.0, 1.0)},
)
state_manager = AsyncFileStateManager("processed_arxiv_ids.txt", "pipeline_meta.json")
```

该导出器沿用了旧的合并规则：每个规范化名称一行，之后的记录只填补空单元格，值被转换为浮点数，
`numeric_clip` 替代了手写的暗物质比例截断。它还会串行化并发导出，并以原子重命名的方式发布
每个快照。

**检查现有的状态文件能否原样复用。** udg-catalogue 的可以：`processed_arxiv_ids.txt` 中
已经是 `2607.14209v1` 这样带版本号的裸 id，正是 `AsyncArxivExtractor` 产生的格式；
`pipeline_meta.json` 中也已经有 `AsyncFileStateManager` 读取的 `last_run_date` 和
`last_start_index` 键。把状态管理器指向旧文件，就在没有任何导入脚本的情况下沿用了全部 542 篇
已处理论文。如果你的 id 以 URL 形式存储，或者不带版本后缀，请先转换，否则每篇论文都会被重新
处理。

续跑方面有两处细节发生了变化：

- **最新优先的列表。** arXiv 先列出最新的投稿，因此保存的偏移量会随着新论文的到来而漂移。
  现在 `main.py` 默认传入 `start_index=0`，从最新的投稿开始重新扫描，同时按 id 跳过已处理的
  论文；重新扫描只消耗列表请求，不消耗 LLM 调用。`python main.py --resume` 则改用保存的
  偏移量。
- **偏移量只会越过已落定的页面。** 旧循环在每页之后都给偏移量加 500，即使该页上有论文失败。
  本库只有在页上每篇论文都已处理或被判定为不相关时，才会越过该页。

## 第 7 步：后处理 {#step-7-post-processing}

**迁移前**（`data_processor.py`，有删节）：去重会先备份一个 `.bak`，然后就地改写原始 CSV，
`process_database` 依次运行一系列函数。

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

**迁移后**（`udg_catalogue/postprocess.py`）：同样的步骤序列写成 `ProcessorChain`，原始 CSV
保持不变，只写出排好序的星表。

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

`CompletenessStep`、`QualityFlagStep`、`NormalizationStep`、`DeduplicationStep` 和
`ClusteringStep` 来自本库。科学部分通过两个小接口接入。`SkyPositionMatcher` 告诉
`DeduplicationStep` 哪些行在天球上是同一个天体：

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

`CartesianDistanceFeatures` 为 `ClusteringStep` 提供由赤经、赤纬和距离构建的三维位置。
`ConstellationStep`、`ValueClipStep` 和 `CatalogueLayoutStep` 是保留在项目中的普通
`Processor`：`Processor` 只需返回一个新的 DataFrame，而不修改其输入。

把原始 CSV 作为导出器的唯一事实来源，并从中派生出排序后的文件，可以让后处理可重复执行：
`python main.py --skip-ingestion` 无需访问 arXiv 或 LLM 即可重建所有输出。

## 第 8 步：先核对结果一致，再改变行为 {#step-8-check-parity-before-changing-behavior}

让旧代码与新代码并存且都能运行，并给两者相同的输入。不需要安装旧项目：用
`git show <commit>:data_processor.py` 把旧模块从 Git 导出到一个临时文件夹，再从那里导入。

udg-catalogue 做了四项核对。

**导出重放。** 把现有星表的每一行随机拆成两条不完整的提取记录，再加入几条手写的无效记录，
然后把打乱顺序的记录分批分别送入旧的 upsert 和新的校验器与导出器：

```python
for batch in batches:
    data_processor.upsert_to_csv([dict(record) for record in batch])

for batch in batches:
    await exporter.export([record for record in batch if validator.is_valid(record)], "new.csv")
```

**后处理。** 旧的 `clean_duplicates` 和 `process_database` 与新的处理链在同一份原始星表的
副本上运行，并逐个单元格比较排序后的输出。要比较聚类的*成员*，而不是聚类 id：DBSCAN 按遇到
聚类的顺序为其编号。

**全文。** 新旧两种获取方式都获取了同样的三篇近期论文。

**实际运行。** 用较小的 `page_size` 和 `total_limit`，在一个全新的状态文件夹中，让组装好的
流水线对 arXiv 和 DeepSeek 实际运行。

| 核对项 | 结果 |
|--------|------|
| 导出重放：735 批共 2,581 条记录 | CSV 完全相同 |
| 导出重放（同一篇论文中某个星系重复出现） | 合并旧 upsert 产生的 2 个重复行后完全相同 |
| 对含 1,285 个星系的星表做后处理 | 逐单元格相同，包括行顺序和聚类 id，只有 3 行赤经超过 360° 的数据例外 |
| 3 篇近期论文的全文 | LaTeX 文本逐字节相同 |
| 实际运行 | arXiv 对每次列表请求都返回 `429`，`run()` 抛出 `PipelineAborted` 且没有写入任何内容，而不是报告成功；第 3 步中更长的退避正是由此而来 |
| 项目测试套件 | 84 个离线测试，覆盖率 100%，无论使用可编辑安装的库，还是在从仓库内 wheel 安装的干净环境中，都能通过 |

只有在这些核对全部一致之后，才把规范化器的修复作为一项单独的变更提交。用它重新生成排序后的
星表时，唯一的差异是那三行赤经无效的数据、成员不变但重新编号的聚类，以及被删除的
`filled_fields` 列。

运行迁移后的流水线时：

- 在日志中搜索 `Record processing failed`。这些记录没有被标记为已处理，下一次运行会重试
  它们。
- 如果 `run()` 抛出 `PipelineAborted`，请查看该异常的 `__cause__`：API 密钥被拒绝、CSV 无法
  读取或列表请求被限流，都会显示在那里。
- 如果你编写了自己的组件，请对照[添加新组件](../project/contributing.md#adding-a-new-component)
  中的契约检查它们。

## 第 9 步：删除旧代码 {#step-9-delete-the-old-code}

核对通过后，删除被本库替代的内容。udg-catalogue 删除了 `arxiv_client.py`、
`data_processor.py`、`config.py`、`logger.py`、`incremental.py`、重复的模拟关键词模式以及
未使用的过滤提示词，还有那些模拟 `requests` 和线程池的测试。剩下的是一个由领域模块（配置、
提示词、命名、校验、天体测量、后处理、地图、分析）组成的 `udg_catalogue` 包，以及一套离线
运行真实流水线的测试。

`visualization.py` 和仪表盘过去会把同一张 Plotly 图构建两次；迁移正是为它们提供一个共用图表
构建器的好时机。没有使用 `AsyncPlotly3DExporter`，因为 udg-catalogue 的地图需要自定义悬停
文本和固定的颜色范围。

## 升级项目 {#upgrading-the-project}

第 1 步锁定了一个版本范围，并且只有在用项目测试验证过新的次版本之后才提高上限。
[迁移指南](../project/migration.md)列出了每个版本的变更；本节记录这些变更对 udg-catalogue
意味着什么。

### 迁移到 0.4 {#moving-to-04}

udg-catalogue 跳过了 0.3：它的 `build_pipeline` 没有传入 `memory_ingestor`，
`AsyncFileStateManager` 也没有变化，因此 0.3 中的任何内容都不影响它。它从 `>=0.2.0,<0.3`
直接升到了 `>=0.4.0,<0.5`，并添加了 `embeddings`、`embeddings-local` 和 `search` extra：

```text
sci-etl-core[async,llm,pdf,cluster,embeddings,embeddings-local,search]>=0.4.0,<0.5
```

升级到 0.4 后，前面各步让项目编写的若干代码可以去掉了：

- **改名的流水线设置。** 0.2 的 `build_pipeline` 和 `run_ingestion` 在 0.4 上会发出警告，
  因为 `max_records` 和 `max_workers` 已改为 `total_limit` 和 `max_concurrency`。
  udg-catalogue 在 `config.yaml` 中改了这两个键的名称。
- **不再需要流水线子类。** `PipelineConfig` 增加了 `page_size`、`search_delay` 和
  `newest_first`，因此删除了第 2 步中的 `CataloguePipelineConfig`，`CatalogueConfig` 直接
  使用本库的 `pipeline` 部分。
- **无需包装层的校验。** udg-catalogue 把 `build_galaxy_validator()` 和
  `label_field=KEY_COLUMN` 传给 `AsyncLLMEntityExtractor`，并删除了第 5 步中的
  `ValidatedEntityExtractor`。
- **最新优先的续跑。** udg-catalogue 设置了 `pipeline.newest_first: true`，因此现在
  `python main.py` 默认就会续跑；第 6 步中的 `--resume` 参数已被移除，`--rescan` 则传入
  `start_index=0` 和 `newest_first=False` 来翻阅整个列表。
- **缓存、关闭和运行摘要。** udg-catalogue 把它的 LLM 客户端包装在以
  `AsyncSqliteLLMResponseCache` 为后端的 `CachingLLMClient` 中，因此崩溃后重新运行不会为
  同样的相关性判断和提取调用付两次费用。它传入一个 `ShutdownSignal`，`main.py` 在遇到
  `PipelineInterrupted` 时以代码 130 退出。`on_event` 回调会记录每个 `PageFinished`，而
  `RunFinished` 事件中的 `RunMetrics`（包括来自 `usage_sources` 的 token 用量）会成为日志中
  的运行摘要。
- **绘图。** `ScatterPlotConfig` 增加了自定义悬停文本和固定颜色范围，正是缺少这两项功能，
  才让 udg-catalogue 在第 9 步中没有使用 `AsyncPlotly3DExporter`。
- **截断与表格布局。** udg-catalogue 删除了第 7 步中它自己的 `ValueClipStep` 和
  `CatalogueLayoutStep`；处理链现在从本库导入 `ValueClipStep`，并以
  `TableLayoutStep(sort_by=SORT_ORDER, leading_columns=LEADING_COLUMNS,
  hidden_prefixes=("_",))` 结尾。

升级之后，udg-catalogue 的流水线组装代码从配置中读取设置，并为每篇相关论文建立检索索引。只
保留摄取分支后，`udg_catalogue/pipeline.py` 是这样构建流水线的：

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

`library.memory_ingestor` 返回一个 `AsyncCompositeIngestor`，它把嵌入后的文本块存入
`AsyncSqliteEmbeddingStore`，并在 `AsyncSqliteFts5Store` 中为论文建立索引；当
`embeddings.enabled` 为 false 时，则只返回 `AsyncSearchIndexer`。运行本身精简为一个
`async with` 代码块：

```python
async def _run(build, config, logger, start_index, shutdown):
    library = open_paper_library(config)
    http_client = build_http_client(config)
    llm_client = build_llm_client(config)
    async with build(config, logger, http_client, llm_client, library, shutdown) as pipeline:
        return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

升级之前筛选过的论文从未建立索引，而 udg-catalogue 也没有可供回填的向量记忆。
`python main.py --index-papers` 会通过同一条流水线重新获取这些论文，使用一个什么都不返回的
实体提取器、一个跳过已在文本索引中的论文的相关性过滤器，以及一个独立的状态管理器
（`indexed_arxiv_ids.txt`、`indexing_meta.json`），因此星系星表及其已处理 id 都不受影响。

### 迁移到 0.5 {#moving-to-05}

udg-catalogue 升级到了 `>=0.5.1,<0.6`。有两项变更影响到它：

- **严格的配置。** 本库的配置部分会拒绝未知的键，udg-catalogue 也把自己的配置部分
  （`paths`、`embeddings`、`clustering`、`deduplication`）设为严格模式，因此 `config.yaml`
  中的拼写错误会在启动时报错并指出键名。0.2 的名称 `max_records` 和 `max_workers` 不再能
  加载。
- **已解析的列表页。** 提取器从 `fetch_page(query, cursor, page_size)` 返回 `ListingPage`，
  而不再从 `search` 和 `parse_listing` 返回原始字节，因此项目中记录每次列表请求的包装层改为
  转发 `cursor_for_offset` 和 `fetch_page`。

### 迁移到 0.6 {#moving-to-06}

udg-catalogue 升级到了 `>=0.6.0,<0.7`。自 0.6 起，基础安装只需要 Pydantic，因此项目列出了
它导入的每个 extra，新增了 `config`（YAML 和 `.env`）、`arxiv`（Atom 解析）、`html` 以及
`processors`（pandas）：

```text
sci-etl-core[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]>=0.6.0,<0.7
```

升级的其余部分改变了星表所记录的内容：

- **每篇论文中的每个星系一行。** `AsyncCsvUpsertExporter` 已被移除。`AsyncCsvExporter` 为
  每个星系写一行，并标上论文的 `record_id`，从不合并、截断或转换任何值；论文被重新提取时，
  会替换该论文的行。所有合并操作都移到了后处理中。0.5 写出的原始星表没有 `record_id` 列，
  因此需要从头重建一次星表；后处理遇到旧的原始文件时会拒绝处理，并给出说明此情况的消息。
- **每个星系背后的论文。** 后处理链以一个小小的 `RawRowsStep` 开头，它把 `record_id` 和
  `extra` 隐藏为 `_record_id` 和 `_extra`，并把测量值读作数字。随后
  `DeduplicationStep(source_column="_record_id", sources_column="source_papers")` 会在已
  发布的星表中列出合并进每个星系的论文。
- **带原因的拒绝，保留以供复核。** `GalaxyValidator.validate` 返回一个 `Violation`，其代码
  指明被违反的规则（`no-name`、`paper-local-name`、`simulation-keyword`、`not-a-number`、
  `not-positive`、`out-of-range` 或 `no-measurement`），而 `is_valid` 只能给出 `False`。
  提取器会连同原因记录每次拒绝，并把它存入 `AsyncSqliteRejectionStore`，复核者可以在那里
  列出并处理它。
- **标准日志。** `logger=` 参数和 `configure_logging` 已被移除。项目的
  `configure_run_logging` 把运行日志的处理器挂到它自己的记录器和 `sci_etl_core` 上，并用
  一个 `logging.Filter` 在本库输出的每一行前面加上正在处理的论文的 arXiv id。
- **建立索引永远不会触及星表。** `--index-papers` 运行过去会把星表导出器与一个什么都不返回
  的提取器一起传入。自 0.6 起，流水线会写入每条已处理的记录（包括没有实体的记录），而这样的
  写入会清除该论文的行。因此，建立索引的流水线改用一个什么都不保留的导出器：

    ```python
    class DiscardingExporter(AsyncExporter[Any]):
        async def write(self, record: RawRecord, entities: Sequence[Any]) -> None:
            return None
    ```

- **运行清单。** 每次构建之后，`write_manifest` 会在 `data/run_manifest.json` 中记录
  sci-etl-core 版本、模型和基础 URL、两条提示词的哈希、查询、已处理的 arXiv id，以及两份
  星表的行数和 SHA-256；该文件与已发布的星表一起提交。

## 迁移中发现的问题 {#what-the-migration-uncovered}

把代码迁移到共享组件上，会迫使你精确地表述每一条规则。udg-catalogue 的迁移暴露了以下问题，
其中大多数在旧的输出中是看不出来的：

1. **名称匹配把不同的星系合并在了一起。** 旧的规范化器会把任何含有数字的名称（VCC 名称
   除外）映射为键 `dragonfly<第一个数字>`：1,285 个已存储名称中有 1,201 个（93%）如此。
   `KDG 44` 与 `DF 44` 匹配，`NGC 1052-DF2` 与 `NGC 1052-DF4` 匹配，于是 upsert 悄无声息地
   用一个星系的测量值填补了另一个星系的空缺。修复后的规范化器让全部 1,285 个已存储名称保持
   不同，但之前的运行已经合并的行，只能通过重新提取星表才能分开。
2. **失败看起来像成功。** 九次 arXiv 检索失败让运行像列表已耗尽一样结束，8 次 DeepSeek
   错误则让论文在什么都没提取的情况下被标记为已处理。
3. **并发写入 CSV 没有加锁。** 六个线程改写同一个 CSV，日志中记录了该循环里的 8 次工作线程
   异常。
4. **e-print 下载禁用了 TLS 校验。**
5. **upsert 会重复同一篇论文的提取结果中被提到两次的星系**，这只有导出重放才发现了。
6. **有三个已存储星系的赤经超过 360°。** 旧的星座步骤会悄悄地对它们取模；现在它们被报告为
   `Unknown`。
7. **在 README 所写的 Python 版本上，锁定的依赖版本无法安装**：`numpy==1.22.0` 没有
   Python 3.11 的 wheel，而 `pandas==2.0.0` 在该版本上需要更新的 numpy。
8. **工作区移到另一个文件夹后，可编辑安装失效了。**

## 将其应用到你的领域 {#adapting-this-to-your-field}

- [ ] 列出你流水线中的每个函数，并按照[把你的流水线对应到本库](#map-your-pipeline-onto-the-library)
      中的三类进行归类。
- [ ] 以可编辑模式安装本库，并决定部署环境如何获取它（从 PyPI 获取一个版本范围，或者在无法
      访问 PyPI 的地方使用仓库内的 wheel）。
- [ ] 把设置迁移到 `BaseAppConfig` 的各个部分中；用 `api_key_env_var` 保留 API 密钥环境变量的
      名称。
- [ ] 原样迁移提示词，并把 `result_key` 设为你的提取提示词已经要求的列表键。
- [ ] 把名称匹配规则移植为 `KeyNormalizer`，把记录规则移植为 `RecordValidator`，一开始不做
      任何修改。
- [ ] 在编写导入脚本之前，先检查你的已处理 id 文件和偏移量文件是否已经符合状态管理器的格式。
- [ ] 把后处理表达为 `ProcessorChain`，把领域逻辑放在 `NeighborMatcher`、`FeatureExtractor`
      和 `Processor` 插件中。
- [ ] 用真实数据分别重放旧代码和新代码，并比较输出。
- [ ] 只有在此之后，才逐个提交地修复你发现有问题的规则。
- [ ] 删除旧代码以及只覆盖旧代码的测试。

在迁移中有疑问，或遇到了不顺手的地方？请提交一个
[issue](https://github.com/xueromll/sci-etl-core/issues)，我们乐意提供帮助。
