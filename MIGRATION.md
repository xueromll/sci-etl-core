# Migrating a Pipeline to sci-etl-core

This guide moves an existing research pipeline onto `sci-etl-core`, using one
real migration as the worked example:
[udg-catalogue](https://github.com/xueromll/udg-catalogue), which builds a
catalogue of ultra-diffuse galaxies (UDGs) from arXiv papers with an LLM.

Every "before" snippet is taken from udg-catalogue as it was before the
migration. Every "after" snippet in Steps 1 to 9 is taken from the migrated
project on sci-etl-core 0.2, at
[commit `8cd9471`](https://github.com/xueromll/udg-catalogue/tree/8cd94711b864212a8fa0d55d60f51e500cf42ec3).
[Upgrading to 0.4](#upgrading-to-04) shows how that code changed on the
project's [`main` branch](https://github.com/xueromll/udg-catalogue/tree/main).
The science is astronomy, but nothing in the steps depends on it: swap the
prompts, fields, and domain rules for your own.

- [The project before](#the-project-before)
- [Where you'll end up](#where-youll-end-up)
- [Map your pipeline onto the library](#map-your-pipeline-onto-the-library)
- [Step 1: Install and link the library](#step-1-install-and-link-the-library)
- [Step 2: Configuration and secrets](#step-2-configuration-and-secrets)
- [Step 3: Source and full text](#step-3-source-and-full-text)
- [Step 4: The LLM steps](#step-4-the-llm-steps)
- [Step 5: Domain rules as plug-ins](#step-5-domain-rules-as-plug-ins)
- [Step 6: Export and state](#step-6-export-and-state)
- [Step 7: Post-processing](#step-7-post-processing)
- [Step 8: Check parity before changing behavior](#step-8-check-parity-before-changing-behavior)
- [Step 9: Delete the old code](#step-9-delete-the-old-code)
- [Upgrading to 0.3](#upgrading-to-03)
- [Upgrading to 0.4](#upgrading-to-04)
- [Upgrading to 0.5](#upgrading-to-05)
- [What the migration uncovered](#what-the-migration-uncovered)
- [Adapting this to your field](#adapting-this-to-your-field)

---

## The project before

udg-catalogue searches arXiv for `cat:astro-ph.GA AND abs:ultra-diffuse`. For
each paper it asks an LLM whether the abstract reports real observations,
downloads the LaTeX source or PDF, asks the LLM to extract every galaxy as
JSON, and merges the galaxies into a CSV. A post-processing step then removes
duplicates, scores completeness, assigns constellations and 3D clusters, and
writes the sorted catalogue behind a Streamlit dashboard.

The ETL machinery lived in flat modules at the project root:

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `arxiv_client.py` | 198 | arXiv search and Atom parsing, LaTeX and PDF download, table extraction, reference trimming, both LLM calls |
| `data_processor.py` | 314 | processed-id file, galaxy validation, CSV upsert, deduplication, completeness, constellations, clustering, quality flags |
| `main.py` | 94 | paging loop over a `ThreadPoolExecutor` |
| `config.py`, `logger.py`, `incremental.py` | 97 | YAML read into module constants, logging setup, resume offset |

The orchestration loop in `main.py` looked like this:

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

## Where you'll end up

After the migration, the whole ingestion side is one function that wires
library components together. This is `udg_catalogue/pipeline.py`:

```python
def build_catalogue_exporter() -> AsyncCsvUpsertExporter:
    return AsyncCsvUpsertExporter(
        key_column=KEY_COLUMN,
        value_columns=list(MEASUREMENT_FIELDS),
        normalizer=GalaxyNameNormalizer(),
        numeric_clip=dict(FRACTION_BOUNDS),
    )


def build_pipeline(
    config: CatalogueConfig,
    logger: logging.Logger,
    http_client: httpx.AsyncClient,
    llm_client: AsyncLLMClient,
) -> AsyncETLPipeline:
    extractor = AsyncArxivExtractor(
        client=http_client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        max_retries=config.http.max_retries,
        backoff_factor=config.http.backoff_factor,
        sleep_before_search=config.pipeline.search_delay,
        logger=logger.info,
    )
    entity_extractor = ValidatedEntityExtractor(
        AsyncLLMEntityExtractor(
            llm_client=llm_client,
            system_prompt=EXTRACTION_PROMPT,
            result_key=EXTRACTION_RESULT_KEY,
            timeout=config.llm.timeout,
        ),
        build_galaxy_validator(),
        logger=logger.info,
    )
    return AsyncETLPipeline(
        extractor=extractor,
        relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm_client, system_prompt=RELEVANCE_PROMPT),
        entity_extractor=entity_extractor,
        exporter=build_catalogue_exporter(),
        state_manager=AsyncFileStateManager(config.paths.processed_ids, config.paths.pipeline_metadata),
        destination=str(config.paths.raw_catalogue),
        max_concurrency=config.pipeline.max_workers,
        logger=logger.warning,
        closeables=[http_client, llm_client],
    )


async def run_ingestion(config: CatalogueConfig, logger: logging.Logger, start_index: int | None = 0) -> int:
    http_client = build_async_client(timeout=config.http.timeout, user_agent=config.http.user_agent)
    llm_client = AsyncOpenAICompatibleClient(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        default_timeout=config.llm.timeout,
    )
    async with build_pipeline(config, logger, http_client, llm_client) as pipeline:
        return await pipeline.run(
            query=config.pipeline.search_query,
            page_size=config.pipeline.page_size,
            total_limit=config.pipeline.max_records,
            sleep_between=config.pipeline.sleep_between,
            start_index=start_index,
        )
```

`build_pipeline` takes the HTTP and LLM clients as arguments, so the project's
tests pass in an `httpx.MockTransport` that serves a fake Atom feed and
e-print, plus a scripted `AsyncLLMClient`, and run the real pipeline offline.

`main.py` shrinks to loading the config, running ingestion, and building the
outputs:

```python
config = load_catalogue_config(arguments.config)
log = configure_logging(LOGGER_NAME, config.paths.log_file)
processed = asyncio.run(run_ingestion(config, log, start_index))
catalogue = build_sorted_catalogue(config, log.info)
```

What stays in the project is the part only an astronomer can write: prompts,
the rules for naming and validating galaxies, sky-position matching, the
features used for clustering, and the dashboard.

## Map your pipeline onto the library

Start by sorting every function in the old pipeline into one of three groups:
replaced by a library component, replaced by a library component plus a small
plug-in, or kept.

| Before (udg-catalogue) | After | What you still write |
|------------------------|-------|----------------------|
| `search_arxiv`, `parse_arxiv_xml` | `AsyncArxivExtractor` | nothing |
| `fetch_paper_text`, `extract_tables_from_pdf`, `trim_references` | `AsyncArxivExtractor` with `LatexTarballParser` and `PdfPlumberParser` | nothing |
| `requests` session with `Retry` | `build_async_client` | nothing |
| `is_paper_relevant` | `AsyncLLMRelevanceFilter` | the prompt |
| `extract_udg_data` | `AsyncLLMEntityExtractor(result_key="galaxies")` | the prompt |
| OpenAI client pointed at DeepSeek | `AsyncOpenAICompatibleClient` | base URL and model |
| `upsert_to_csv` | `AsyncCsvUpsertExporter` | key column, value columns, clip bounds |
| `load_processed_ids`, `save_processed_id`, `incremental.py` | `AsyncFileStateManager` | file paths |
| `main.py` loop | `AsyncETLPipeline` | the wiring above |
| `logger.py` | `configure_logging` | nothing |
| `config.py` | `BaseAppConfig` subclass and `load_config` | project settings |
| `universal_normalize_name` | `KeyNormalizer` subclass | name-matching rules |
| `is_valid_galaxy` | `CompositeValidator` of `RecordValidator`s | field rules, plus a small extractor wrapper |
| `clean_duplicates` | `NormalizationStep` and `DeduplicationStep` | a `NeighborMatcher` for sky positions |
| `calculate_completeness`, `assign_quality_flag` | `CompletenessStep`, `QualityFlagStep` | the field list |
| `assign_3d_clusters` | `ClusteringStep` | a `FeatureExtractor` for 3D positions |
| `assign_constellations`, plots, dashboard | kept | domain code, as `Processor`s where it fits |

## Step 1: Install and link the library

You will change both codebases while migrating, so install the library in
editable mode into the project's environment. udg-catalogue sits two folders
away from its sci-etl-core checkout:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "../../sci-etl-core[async,llm,pdf,cluster]"
python -c "import sci_etl_core; print(sci_etl_core.__file__)"
```

On Windows, activate with `.venv\Scripts\activate`. The last command should
print a path inside the checkout's `src` folder. Choose extras for the
components you use: udg-catalogue needs `async` for the arXiv extractor and
CSV exporter, `llm` for the OpenAI-compatible client, `pdf` for
`PdfPlumberParser`, and `cluster` for `ClusteringStep`.

An editable install records the checkout's absolute path. If you move or
rename the library folder, `import sci_etl_core` fails until you reinstall;
this is exactly what happened when the udg-catalogue workspace moved into a
synced OneDrive folder.

Deployed environments can't see a sibling checkout, and pip can't install one
package from two sources in the same resolve. udg-catalogue therefore keeps its
pinned third-party packages in `requirements-app.txt` and chooses the library's
source in two thin files. For local development, `requirements-local.txt`:

```text
-r requirements-app.txt
-e ../../sci-etl-core[async,llm,pdf,cluster]
```

For Docker, CI, and new users, `requirements.txt` installs the published
release from PyPI:

```text
-r requirements-app.txt
sci-etl-core[async,llm,pdf,cluster]>=0.2.0,<0.3
```

Pin a version range rather than one exact version, so bug-fix releases arrive
without a change to the project, and raise the upper bound deliberately after
checking a new minor release against your tests. Before the library was on
PyPI, udg-catalogue committed a wheel built with
`pip wheel --no-deps -w vendor path/to/sci-etl-core` and installed it from
`vendor/`; that still works for a build that can't reach PyPI.

## Step 2: Configuration and secrets

**Before** (`config.py`): the YAML was read into module-level constants when
the module was imported.

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

**After**: `config.yaml` uses the library's sections (`llm`, `http`,
`pipeline`) plus the project's own (`paths`, `clustering`, `deduplication`):

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

`udg_catalogue/config.py` subclasses the library models:

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

Three choices here are worth copying:

- **Keep your secret's name.** `api_key_env_var="DEEPSEEK_API_KEY"` means the
  existing `.env` file and the Docker Compose file keep working unchanged. The
  key is held as a `SecretStr`, so it never shows up in reprs or logs.
- **Extend sections by subclassing.** `CataloguePipelineConfig` adds
  `page_size` and `search_delay` while keeping every field the library reads.
- **Resolve paths from the config file.** Passing the `.env` beside the config
  explicitly, and anchoring relative paths to the config's folder, means the
  pipeline behaves the same whichever directory you start it from. The old
  code resolved most paths from the script folder but `pipeline_meta.json` and
  `analysis/` from the working directory.

Config values aren't applied automatically: pass them to constructors and to
`run()`, as `build_pipeline` does.

## Step 3: Source and full text

**Before** (`arxiv_client.py`, trimmed):

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

**After**:

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

What changed in behavior:

- **A failed search is an error, not the end of the data.** `search_arxiv`
  returned `None`, and the loop in `main.py` treated that as "no more papers"
  and went on to report success. The old log shows 9 runs that stopped this
  way. `AsyncETLPipeline.run()` now raises `PipelineAborted`, and `main.py`
  exits with status 1.
- **Retries wait longer than the defaults.** The extractor waits
  `backoff_factor ** attempt` seconds between attempts, so the default factor
  of 2 waits 1 s and then 2 s. arXiv throttles with `429` for longer than
  that, and the old code waited 20 s after a 429, so udg-catalogue sets
  `backoff_factor: 5.0` and `max_retries: 4` (waits of 1, 5, and 25 s).
- **TLS verification is back on.** The old e-print download used
  `verify=False`.
- **More submissions yield LaTeX.** A single gzipped `.tex` file is read
  instead of failing over to the PDF, and multi-file sources are assembled in
  `\input` order.
- **Everything else is the same.** The reference-trimming patterns are the
  same seven expressions, and the PDF parser appends tables under the same
  `--- EXTRACTED TABLES ---` marker. For three recent papers, old and new code
  returned byte-identical text.

## Step 4: The LLM steps

**Before** (`arxiv_client.py`, trimmed):

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
    ...
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return []
```

**After** (the same calls as in `run_ingestion` and `build_pipeline`, pulled
out into variables):

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

The prompts moved into `udg_catalogue/prompts.py` character for character.
They already mentioned JSON, which JSON mode requires, and the extraction
prompt already asked for `{"galaxies": [...]}`, so `result_key="galaxies"`
reads that shape and the prompt didn't have to change. The 120,000-character
cap, the HTML stripping, and the temperature of 0 are the library's defaults
too.

What changed in behavior:

- **Relevance still fails open.** A failed call lets the paper through, as
  before, and the timeout is still 20 s. One difference: a reply with no clear
  verdict now also lets the paper through, where the old code read a missing
  `relevant` key as `False`. Pass `default_on_error=False` to drop such papers.
- **Extraction failures are retried.** `extract_udg_data` returned `[]` when
  DeepSeek failed, so the paper was marked processed with nothing extracted;
  the old log shows 8 such papers that will never be revisited.
  `AsyncLLMEntityExtractor` raises `LLMError`, the pipeline leaves the paper
  unmarked, and the next run tries it again.

## Step 5: Domain rules as plug-ins

The rules that decide what counts as the same galaxy, and what counts as a
real one, are science, and they stay in the project. The library gives them a
place to plug in.

### Name matching: a `KeyNormalizer`

**Before** (`data_processor.py`):

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

Port a function like this **unchanged** first, as a `KeyNormalizer` subclass,
so the parity check in Step 8 compares plumbing and nothing else.
udg-catalogue did exactly that.

This function turned out to merge different galaxies (see
[What the migration uncovered](#what-the-migration-uncovered)), so it was
replaced once parity was confirmed. **After**
(`udg_catalogue/naming.py`):

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

`DF 44`, `DF044`, and `Dragonfly 44` still share the key `df44`, while
`KDG 44`, `NGC 1052-DF2`, and `NGC 1052-DF4` now keep keys of their own.
Delegating the missing-value check to `DefaultKeyNormalizer` means `None`,
`NaN`, and non-scalar values are handled the way every library component
expects. The CSV exporter and the post-processing deduplication both use
`GalaxyNameNormalizer`, so the two stages always agree on identity.

### Validation: `RecordValidator`s and a wrapper

**Before** (`data_processor.py`): validation was buried inside
`upsert_to_csv`.

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

**After** (`udg_catalogue/validation.py`): the library's validators cover the
keyword and range rules, and one small class covers the rest.

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

`AsyncETLPipeline` doesn't call validators itself, so a thin
`AsyncEntityExtractor` applies them between extraction and export and logs
what it drops:

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

Before relying on `KeywordExclusionValidator` in place of the old regular
expression, check the two against your existing data. For udg-catalogue they
agreed on all 1,285 stored names and on edge cases such as `TNG50-1`,
`illustris_galaxy_1`, and `Firefly 7`.

## Step 6: Export and state

**Before** (`data_processor.py` and `incremental.py`, trimmed): each worker
thread read the whole CSV, changed it, and wrote it back, with no lock between
the six threads.

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

**After** (`build_catalogue_exporter` and the state manager from
`build_pipeline`, with the constants from `udg_catalogue/config.py` and the
default paths written out):

```python
exporter = AsyncCsvUpsertExporter(
    key_column="galaxy_name",
    value_columns=["ra", "dec", "distance_mpc", "effective_radius_kpc", "stellar_mass_solar", "dark_matter_fraction"],
    normalizer=GalaxyNameNormalizer(),
    numeric_clip={"dark_matter_fraction": (0.0, 1.0)},
)
state_manager = AsyncFileStateManager("processed_arxiv_ids.txt", "pipeline_meta.json")
```

The exporter keeps the old merge rule: one row per normalized name, later
records only fill empty cells, values are converted to floats, and
`numeric_clip` replaces the hand-written clamp on the dark-matter fraction. It
also serializes concurrent exports and publishes each snapshot with an atomic
rename.

**Check whether your existing state files can be reused as they are.**
udg-catalogue's could: `processed_arxiv_ids.txt` already held bare versioned
ids such as `2607.14209v1`, the format `AsyncArxivExtractor` produces, and
`pipeline_meta.json` already had the `last_run_date` and `last_start_index`
keys `AsyncFileStateManager` reads. Pointing the state manager at the old files
carried all 542 processed papers over with no import script. If your ids are
stored as URLs or without the version suffix, convert them first, or every
paper is processed again.

Two resume details changed:

- **Newest-first listings.** arXiv lists the newest submissions first, so a
  saved offset drifts as new papers arrive. `main.py` now passes
  `start_index=0` by default, rescanning from the newest submission while
  skipping processed papers by id; a rescan costs listing requests, not LLM
  calls. `python main.py --resume` uses the saved offset instead.
- **Offsets only move past settled pages.** The old loop added 500 to the
  offset after every page, even when papers on it had failed. The library only
  advances past a page once every paper on it is processed or ruled irrelevant.

## Step 7: Post-processing

**Before** (`data_processor.py`, trimmed): deduplication rewrote the raw CSV in
place after taking a `.bak` copy, and `process_database` ran a sequence of
functions.

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

**After** (`udg_catalogue/postprocess.py`): the same sequence as a
`ProcessorChain`, with the raw CSV left untouched and only the sorted
catalogue written.

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

`CompletenessStep`, `QualityFlagStep`, `NormalizationStep`,
`DeduplicationStep`, and `ClusteringStep` come from the library. The science
plugs in through two small interfaces. `SkyPositionMatcher` tells
`DeduplicationStep` which rows are the same object on the sky:

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

`CartesianDistanceFeatures` gives `ClusteringStep` 3D positions built from
right ascension, declination, and distance. `ConstellationStep`,
`ValueClipStep`, and `CatalogueLayoutStep` are ordinary `Processor`s kept in
the project: a `Processor` only has to return a new DataFrame without mutating
its input.

Keeping the raw CSV as the exporter's source of truth, and deriving the sorted
file from it, makes post-processing repeatable: `python main.py
--skip-ingestion` rebuilds every output without touching arXiv or the LLM.

## Step 8: Check parity before changing behavior

Keep the old code runnable next to the new code and feed both the same inputs.
You don't need the old project installed: export the old modules from Git
into a scratch folder with `git show <commit>:data_processor.py`, and import
them from there.

udg-catalogue ran four checks.

**Export replay.** Each row of the existing catalogue was split at random into
two partial extraction records, a few hand-written invalid records were added,
and the shuffled records were fed in batches through both the old upsert and
the new validator and exporter:

```python
for batch in batches:
    data_processor.upsert_to_csv([dict(record) for record in batch])

for batch in batches:
    await exporter.export([record for record in batch if validator.is_valid(record)], "new.csv")
```

**Post-processing.** The old `clean_duplicates` and `process_database` and the
new chain ran on copies of the same raw catalogue, and the sorted outputs were
compared cell by cell. Compare cluster *membership*, not cluster ids: DBSCAN
numbers clusters by the order it meets them.

**Full text.** Old and new retrieval fetched the same three recent papers.

**Live run.** The assembled pipeline ran against arXiv and DeepSeek with a
small `page_size` and `total_limit`, into a fresh state folder.

| Check | Result |
|-------|--------|
| Export replay: 2,581 records in 735 batches | identical CSV |
| Export replay with a galaxy repeated within one paper | identical after merging 2 duplicate rows the old upsert created |
| Post-processing on the 1,285-galaxy catalogue | identical cell for cell, including row order and cluster ids, except 3 rows whose RA exceeds 360° |
| Full text for 3 recent papers | byte-identical LaTeX text |
| Live run | arXiv answered `429` to every listing attempt, and `run()` raised `PipelineAborted` with nothing written, instead of reporting success; this is what prompted the longer backoff in Step 3 |
| Project test suite | 84 offline tests, 100% coverage, passing both with the editable library and in a clean environment installed from the vendored wheel |

Only after these matched did the normalizer fix go in, as a separate change.
Regenerating the sorted catalogue with it, the only differences were the three
invalid-RA rows, renumbered clusters with unchanged membership, and the
dropped `filled_fields` column.

When you run the migrated pipeline:

- Search the log for `Record processing failed`. Those records weren't marked
  processed, and the next run retries them.
- If `run()` raises `PipelineAborted`, read the exception's `__cause__`: a
  rejected API key, an unreadable CSV, or a throttled listing request each show
  up there.
- If you wrote your own components, check them against the contracts in
  [Adding a New Component](CONTRIBUTING.md#adding-a-new-component).

## Step 9: Delete the old code

Once the checks pass, delete what the library replaced. udg-catalogue removed
`arxiv_client.py`, `data_processor.py`, `config.py`, `logger.py`,
`incremental.py`, the duplicated simulation-keyword pattern, and the unused
filter prompt, along with the tests that mocked `requests` and the thread
pool. What remains is a `udg_catalogue` package of domain modules (config,
prompts, naming, validation, astrometry, post-processing, maps, analytics) and
a test suite that exercises the real pipeline offline.

`visualization.py` and the dashboard used to build the same Plotly figure
twice; the migration was a good moment to give them one shared figure builder.
`AsyncPlotly3DExporter` wasn't used, because udg-catalogue's map needs custom
hover text and a fixed color range.

## Upgrading to 0.3

Step 1 pins a version range and raises its upper bound only after checking a
new minor release against your tests: for udg-catalogue, `>=0.2.0,<0.3`
becomes `>=0.3.0,<0.4` once its tests pass on 0.3. The 0.3 release adds local
search and discovery graphs, and changes these things a migrated pipeline can
notice ([CHANGELOG.md](CHANGELOG.md) lists everything):

- **arXiv records carry metadata.** `RawRecord.metadata` now holds
  `categories`, `authors`, `published`, and `year` instead of staying empty.
  Code of your own that reads records, including tests that compare
  `metadata == {}`, sees the new keys. The metadata stored with embedding
  chunks is unchanged.
- **`memory_ingestor` accepts any `MemoryIngestor`.** An `AsyncChunkIngestor`
  works exactly as before. A type hint in your code that names
  `AsyncChunkIngestor` for this argument can widen to `MemoryIngestor`.
- **Search is opt-in.** Nothing changes in a pipeline that passes no text
  index; udg-catalogue's `build_pipeline` passed no `memory_ingestor` at all
  until its 0.4 upgrade.
  To add one, pass an `AsyncSearchIndexer`, or an `AsyncCompositeIngestor`
  with a chunk ingestor first, as
  [Local search and discovery](https://xueromll.github.io/sci-etl-core/latest/guide/search/) shows. Its
  `AsyncSqliteFts5Store` goes in `closeables` like any other SQLite store.
- **SQLite state is safer under cancellation.** `AsyncSqliteStateManager` no
  longer lets a cancelled operation's worker thread overlap the next
  operation. `AsyncFileStateManager`, which udg-catalogue uses, is unchanged.

## Upgrading to 0.4

The 0.4 release adds the PubMed, Semantic Scholar, and OpenAlex extractors,
DOCX and JATS XML parsers, LLM response caching, graceful shutdown, progress
events and run metrics, rate limiters for every HTTP component, `NEAR`
queries, range filters, snippets for every matching field, and backfilling a
text index from the vector memory. udg-catalogue moved from `>=0.2.0,<0.3`
straight to `>=0.4.0,<0.5`, adding the `embeddings`, `embeddings-local`, and
`search` extras:

```text
sci-etl-core[async,llm,pdf,cluster,embeddings,embeddings-local,search]>=0.4.0,<0.5
```

Several of the new features retire code this guide had the project write:

- **Renamed pipeline settings.** `pipeline.max_records` is now `total_limit`
  and `pipeline.max_workers` is `max_concurrency`. The old YAML keys and the
  `PipelineConfig.max_records` and `max_workers` properties still work until
  0.5, with a `DeprecationWarning`, so the 0.2 `build_pipeline` and
  `run_ingestion` shown above warn on 0.4. `run(max_records=)` is deprecated
  the same way. udg-catalogue renamed both keys in `config.yaml`.
- **No pipeline subclass.** `PipelineConfig` now has `page_size`,
  `search_delay`, and `newest_first`, so `CataloguePipelineConfig` from
  Step 2 was deleted and `CatalogueConfig` uses the library's `pipeline`
  section as it is.
- **Validation without a wrapper.** `AsyncLLMEntityExtractor` takes
  `validator=`, `logger=`, and `label_field=`, and logs each entity it drops
  as `Entity rejected by validation: <label>`. udg-catalogue passes
  `build_galaxy_validator()` and `label_field=KEY_COLUMN` and deleted the
  `ValidatedEntityExtractor` from Step 5.
- **Components from the config.** `AsyncArxivExtractor.from_config`,
  `AsyncOpenAICompatibleClient.from_config`, and `AsyncETLPipeline.from_config`
  read the `http`, `llm`, and `pipeline` sections, `config.http.build_client()`
  replaces `build_async_client`, and `config.pipeline.run_arguments()` returns
  the arguments for `run()`, so the settings no longer need copying into
  constructors by hand.
- **Newest-first resume.** `run(newest_first=True)` picks up new arXiv
  submissions without the full rescan that `start_index=0` costs, and saves
  the head of the listing in the metadata file next to `last_start_index`.
  `start_index` can't be combined with it. udg-catalogue sets
  `pipeline.newest_first: true`, so `python main.py` now resumes by default;
  the `--resume` flag from Step 6 is gone, and `--rescan` passes
  `start_index=0` with `newest_first=False` to page the whole listing.
- **Caching, shutdown, and run summaries.** udg-catalogue wraps its LLM client
  in a `CachingLLMClient` backed by an `AsyncSqliteLLMResponseCache`, so a
  rerun after a crash doesn't pay for the same relevance and extraction calls
  twice. It passes a `ShutdownSignal`, and `main.py` exits with code 130 on
  `PipelineInterrupted`. An `on_event` callback logs each `PageFinished`, and
  the `RunFinished` event's `RunMetrics`, including token usage from
  `usage_sources`, becomes the run summary in the log.
- **Plots.** `ScatterPlotConfig` takes `hover_data_columns`,
  `hover_template`, `color_continuous_scale`, and `color_range`, the custom
  hover text and fixed color range that kept udg-catalogue off
  `AsyncPlotly3DExporter`.
- **Clamping and table layout.** `ValueClipStep` clamps columns during
  post-processing, and `TableLayoutStep` sorts rows and orders columns.
  udg-catalogue deleted its own `ValueClipStep` and `CatalogueLayoutStep` from
  Step 7; the chain now imports `ValueClipStep` from the library and ends with
  `TableLayoutStep(sort_by=SORT_ORDER, leading_columns=LEADING_COLUMNS,
  hidden_prefixes=("_",))`.
- **Search from the memory you already have.** A project that stored chunks
  in an `AsyncSqliteEmbeddingStore` can build a text index from them with
  `backfill_text_index` instead of fetching every paper again.
- **Snippets for semantic hits.** A `FusedHit` found only by the semantic leg
  now carries a snippet of its best chunk, where it used to have an empty
  `snippet`. A UI that showed the abstract whenever `snippet` was empty should
  check `lexical_rank is None` instead.
- **Deprecated `requests` helper.** `build_retrying_session` warns and will be
  removed in 0.5, along with `requests` in the `full` extra.

After the upgrade, udg-catalogue's pipeline wiring reads its settings from the
config and indexes every relevant paper for search. Trimmed to the ingestion
branch, `udg_catalogue/pipeline.py` builds the pipeline like this:

```python
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

`library.memory_ingestor` returns an `AsyncCompositeIngestor` that stores
embedded chunks in an `AsyncSqliteEmbeddingStore` and indexes the paper in an
`AsyncSqliteFts5Store`, or just the `AsyncSearchIndexer` when
`embeddings.enabled` is false. The run itself shrinks to one call:

```python
async with build(config, logger, http_client, llm_client, library, shutdown) as pipeline:
    return await pipeline.run(**run_arguments(config.pipeline, start_index))
```

Papers screened before the upgrade were never indexed, and udg-catalogue had
no vector memory to backfill from. `python main.py --index-papers` fetches
them again through the same pipeline with an entity extractor that returns
nothing, a relevance filter that skips papers already in the text index, and
a separate state manager (`indexed_arxiv_ids.txt`, `indexing_meta.json`), so
the galaxy catalogue and its processed ids are left alone.

## Upgrading to 0.5

0.5 changes how extractors page, what the state saves, and how the pipeline
is constructed. Entities and exporters change in 0.6. Require the new minor
and Python 3.11:

```text
sci-etl-core[async,llm,pdf]>=0.5.0,<0.6
```

State written by 0.4 needs no conversion. `AsyncSqliteStateManager` upgrades
its database in place, and `AsyncFileStateManager` reads the old metadata file
and rewrites it in the new format on the next save. Either way the saved offset
becomes the cursor, so the next run resumes where the last one stopped.

### Extractors return parsed pages

`search` and `parse_listing` are replaced by one `fetch_page`, which returns a
`ListingPage`. The pipeline now skips processed records itself, so an
extractor returns every entry it can read. A source that pages by offset
implements `cursor_for_offset` too, which makes it an `OffsetListing`.

Before:

```python
class MyExtractor(AsyncExtractor):
    async def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        return await self._client.get_page(query, start_index, max_results)

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        entries = parse(raw_listing)
        return [entry for entry in entries if entry.record_id not in seen_ids], len(entries)
```

After:

```python
class MyExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return str(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        offset = int(cursor or 0)
        entries = parse(await self._client.get_page(query, offset, page_size))
        return ListingPage(
            records=tuple(entries),
            entries=len(entries),
            next_cursor=str(offset + len(entries)) if entries else None,
        )
```

A source with opaque continuation tokens returns the token as `next_cursor`
and leaves out `cursor_for_offset`. A source that stops at its own result cap
returns `truncated=True` and `next_cursor=None` on the page that reaches it.
Until an extractor is ported, `LegacyExtractorAdapter(MyOldExtractor())` runs
it unchanged in 0.5.x, with a `DeprecationWarning`; 0.6 removes the adapter.

A wrapper that forwards to another extractor, such as a progress logger,
forwards `fetch_page`, and `cursor_for_offset` too when it wraps an
`OffsetListing`:

```python
class LoggingExtractor(AsyncExtractor):
    def cursor_for_offset(self, offset: int) -> str:
        return self._inner.cursor_for_offset(offset)

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        self._log(f"Fetching listing page at cursor {cursor or 'start'}")
        return await self._inner.fetch_page(query, cursor, page_size)
```

`newest_first=True` and `start_index` above 0 need an `OffsetListing` and raise
`ValueError` before any request otherwise. `AsyncArxivExtractor`,
`AsyncPubMedExtractor`, and `AsyncSemanticScholarExtractor` are
`OffsetListing`s. `AsyncOpenAlexExtractor` now pages with OpenAlex cursors, so
it reaches past the first 10,000 works but no longer supports `newest_first`;
its first 0.5 run restarts the listing once from the first page, because the
offset 0.4 saved is not an OpenAlex cursor.

### What the state saves

`PipelineMetadata.cursor` replaces `last_start_index`. Code that reads the
saved position reads the cursor, which is a decimal offset for an
`OffsetListing`:

```python
metadata = await state.load_metadata()
saved_offset = int(metadata.cursor or 0)
```

The progress events gain `cursor`. `RunStarted.start_index`,
`PageFetched.offset`, and `PageFinished.offset` still hold the listing offset
for an `OffsetListing` and are `None` for any other extractor.

### Capped listings start over

PubMed stops at 9,999 results, Semantic Scholar at 1,000. In 0.4 a run that
reached the cap saved the cap as its offset, and every later run ended there at
once. In 0.5 the page that reaches the cap ends the run `"completed"`,
`RunMetrics.listing_truncated` reports it, and the saved cursor is reset, so
the next run pages the reachable results again: processed records are skipped
by id, so the rescan costs listing requests, not LLM calls. Narrow the query,
for example by date, to avoid the rescan.

### Records that keep failing are quarantined

A record that fails in 3 runs, each on a page that processed another record, is
skipped as quarantined from the next run on and counted in
`RunMetrics.quarantined`. Failures on a page where nothing was processed, as
during an outage or with a rejected API key, are never counted. To keep the
0.4 behavior, retrying every failed record forever:

```python
await pipeline.run(query, page_size=100, total_limit=500, max_attempts=None)
```

A third-party state manager keeps working unchanged: the new
`record_failure` and `failure_counts` have defaults that track nothing, so it
never quarantines.

### Keyword arguments

`AsyncETLPipeline` and `ETLPipeline` take the five collaborators positionally,
or by name, and everything else by keyword. `run` takes `query` and then
keywords only, and `max_records=` is gone:

```python
pipeline = AsyncETLPipeline(
    extractor,
    relevance_filter,
    entity_extractor,
    exporter,
    state_manager,
    destination="results.csv",
    max_concurrency=4,
)
await pipeline.run("all:galaxy", page_size=50, total_limit=200)
```

`RawRecord`, `PipelineMetadata`, `TokenUsage`, `RunMetrics`, and the events
are keyword-only, so `RawRecord("id", "title", "abstract")` becomes
`RawRecord(record_id="id", title="title", abstract="abstract")`.

### Strict config sections

A key that a bundled section does not declare now fails validation and is
named in the `ConfigurationError`, so a typo such as `search.bm25.titel` or the
earlier key `pipeline.max_records` no longer passes silently. Rename
`pipeline.max_records` to `total_limit` and `pipeline.max_workers` to
`max_concurrency`. An application that must accept unknown keys for now opts
out on its config class, and each dropped key is reported with a `UserWarning`:

```python
class CatalogueConfig(BaseAppConfig):
    strict_sections = False
```

Top-level sections the application defines are kept as before.

### Table sinks

`AsyncSqlTableExporter` and `AsyncPlotly3DExporter` took a `DataFrame` and
could not run in the pipeline. Their replacements are blocking sinks for
post-processing output:

```python
from sci_etl_core.processors.sinks import Plotly3DSink, ScatterPlotConfig, SqlTableSink

catalogue = chain.process(raw_table)
SqlTableSink("sqlite:///catalogue.db", "galaxies", if_exists="replace").write(catalogue)
Plotly3DSink(ScatterPlotConfig("x", "y", "z", color_column="size"), "catalogue.html").write(catalogue)
```

### Deprecations with no replacement before 0.6

These keep working in 0.5.x and emit a `PendingDeprecationWarning`, not a
`DeprecationWarning`, because their replacements ship in 0.6 and there is
nothing to change yet: the `destination` argument, `AsyncExporter.export` and
`AsyncCsvUpsertExporter` (replaced by the exporter lifecycle and
`AsyncCsvExporter`), and every `logger=` argument and `configure_logging`
(replaced by the standard `logging` module). A test suite run with
`-W error::DeprecationWarning` therefore keeps passing while it uses them.

The blocking contracts and their `Sync*Adapter`s, `LegacyExtractorAdapter`,
and the two table exporters emit a `DeprecationWarning`, because their
replacements exist in 0.5; move to the async contracts, which every component
already implements, `fetch_page`, and the table sinks.

`build_retrying_session` is removed, and the `full` extra no longer installs
`requests`.

## What the migration uncovered

Moving code onto shared components forces you to state every rule precisely.
udg-catalogue's migration surfaced these problems, most of them invisible in
the old output:

1. **Name matching merged different galaxies.** The old normalizer keyed any
   name containing digits, other than VCC names, as `dragonfly<first number>`:
   1,201 of the 1,285 stored names (93%). `KDG 44` matched `DF 44`, and
   `NGC 1052-DF2` matched `NGC 1052-DF4`, so the upsert silently filled one
   galaxy's gaps with another's measurements. The fixed normalizer keeps all
   1,285 stored names distinct, but rows merged by earlier runs can only be
   separated by re-extracting the catalogue.
2. **Failures looked like success.** Nine arXiv search failures ended runs as
   if the listing were exhausted, and 8 DeepSeek errors marked papers processed
   with nothing extracted.
3. **Concurrent CSV writes had no lock.** Six threads rewrote the same CSV, and
   the log records 8 worker exceptions in that loop.
4. **TLS verification was disabled** for e-print downloads.
5. **The upsert duplicated galaxies** named twice in one paper's extraction,
   found only by the export replay.
6. **Three stored galaxies have RA above 360°.** The old constellation step
   wrapped them silently; they are now reported as `Unknown`.
7. **The dependency pins couldn't be installed** on the Python version the
   README named: `numpy==1.22.0` has no Python 3.11 wheels, and
   `pandas==2.0.0` needs a newer numpy there.
8. **An editable install broke** after the workspace moved to another folder.

## Adapting this to your field

- [ ] List every function in your pipeline and sort it into the three groups
      in [Map your pipeline onto the library](#map-your-pipeline-onto-the-library).
- [ ] Install the library in editable mode, and decide how deployments will
      get it (a version range from PyPI, or a vendored wheel where PyPI is
      out of reach).
- [ ] Move settings into `BaseAppConfig` sections; keep your API key's
      environment-variable name with `api_key_env_var`.
- [ ] Move prompts over unchanged, and set `result_key` to the list key your
      extraction prompt already asks for.
- [ ] Port your name-matching rule as a `KeyNormalizer` and your record rules
      as `RecordValidator`s, unchanged at first.
- [ ] Check whether your processed-id and offset files already match the state
      manager's format before writing an import script.
- [ ] Express post-processing as a `ProcessorChain`, with your domain logic in
      `NeighborMatcher`, `FeatureExtractor`, and `Processor` plug-ins.
- [ ] Replay real data through the old and new code and compare the outputs.
- [ ] Only then fix the rules you've found wanting, one commit at a time.
- [ ] Delete the old code and the tests that only covered it.

Questions or a rough edge in your migration? Open an
[issue](.github/ISSUE_TEMPLATE/bug_report.md) — we're happy to help.
