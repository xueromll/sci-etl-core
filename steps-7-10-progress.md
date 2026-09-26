# Steps 7–10 of `audit-analysis.md`: progress handoff

Written 2026-09-26 when the session stopped near the usage limit. Nothing is
committed; every change sits in the working trees. This file is untracked; add
it to `.gitignore` next to the other plan files, or delete it once the work is done.

Sources followed: `audit-analysis.md` §6 steps 7–10, `release-plan.md` §5
(Phase 3), `claims-provenance-plan.md` (phases 0a, 0b, 1). The
`sci-etl-kg-plan.md` needs nothing from 0.6.0 beyond the claims contracts;
kg work stays gated on core 1.0.0 and a second catalog.

## Decisions made along the way

- **Rule numbers.** R19 was already used by 0.5.1 ("settled only on an
  answer"), so the plan's exporter rules R19–R21 became **R20–R23**:
  R20 durability, R21 write and flush faults, R22 open fault, R23 write for
  every processed record. R9 and R10 were amended.
- **The 0.5 deprecations are removed in 0.6.0**, as the audit (step 7 costs)
  and release D28 assume. The step 10 rule "keep deprecations for at least two
  minors" applies from 0.6.0 on; ROADMAP and MIGRATION say so.
- **`AsyncCsvExporter` is long format**, one row per entity with `record_id`
  and `extra`, and never merges, clips, or coerces. This follows the audit's
  "conflict-preserving exporter in long format, replacing first-value-wins",
  which supersedes release-plan §5.2's upsert design. It renders the file
  once per run from an append-only `<path>.journal` and is linear (benchmark
  ratio 0.86 against 4.37 for the old upsert exporter; JSONL 0.93).
- **`AsyncJsonlExporter` writes one line per record** (`entities` list, last
  line wins), so a re-extraction to zero entities is representable.
- **`model` is not a property on the `AsyncLLMClient` ABC** (plan D41): a
  read-only property breaks clients that assign `self.model`. Stamps read
  `getattr(client, "model", "")`.
- **Structured output** goes through a new defaulted method,
  `AsyncLLMClient.complete_structured(system, user, schema, timeout)`, with
  `invalidate(..., schema=)`. `AsyncOpenAICompatibleClient(structured_output=)`
  and `LLMConfig.structured_output` turn on `json_schema` (off by default,
  since DeepSeek lacks it). The schema and `variant` join the cache key only
  when present, so keys without them equal the 0.5.1 keys (a test pins the
  digests).
- **Provisional claims names are not re-exported at top level**; they live
  in `sci_etl_core.claims`.
- **Base install is `pydantic` only.** New extras: `config`, `arxiv`
  (bs4 + lxml), `xml`, `html`, `processors` (pandas + numpy). `aiofiles` and
  `aiosqlite` are gone from every extra. The exit criterion "a bare install
  imports every stable name" was reworded: every stable name imports from a
  bare install **or from the extra its component needs**, and
  `tests/api/import_map.py` now exits 1 on an import failure no extra explains
  (checked on a pydantic-only Python 3.11 venv: 218 of 262 import bare, all
  others explained).
- **`load_config` reads `.env` only with `env_path=` or `load_env=True`.**
- **`ETLPipeline` stays** (OQ-2 left open); it was never deprecated.
- **Release gate (step 10).** 0.5.1's changelog dropped the gate because
  requiring consumers' *pinned* installs is circular. Step 10's form is
  different and workable: the release workflow runs the CLI and udg-catalogue
  test suites against the release commit. ROADMAP "Path to 1.0" already states
  this; the workflow change itself is still TODO.
- **Added to core beyond the plans:** `DeduplicationStep(source_column=,
  sources_column=)` lists every source (paper id) merged into each output row,
  so udg-catalogue's published catalog can say which papers each galaxy came
  from. It is in the CHANGELOG and the post-processing guide.

## sci-etl-core (this repo): DONE

Suite: 2,344+ tests pass at 100% line coverage; ruff and mypy clean;
`-W error::DeprecationWarning -W error::PendingDeprecationWarning` clean.
Run it with the scratch venv or any env with `pip install -e ".[full,dev,lint]"`.

- DONE: version `0.6.0.dev0` in `pyproject.toml` (step 10 dev bump).
- DONE: claims 0a — `Violation`, `ValidationResult`, `RecordValidator.validate`,
  overrides in the bundled validators, collecting `CompositeValidator.validate`.
- DONE: typed entities — generic `AsyncEntityExtractor[E]`,
  `AsyncLLMEntityExtractor(schema=)` (all args after `system_prompt`
  keyword-only), `entity_list_schema`, schema in cache key, `variant=`.
- DONE: claims 0b — `extract_record`, `requires_record`, `prepare`, `stamp`,
  `ExtractionStamp`, `content_hash`, rejection stores (in-memory and SQLite),
  `rejections=`.
- DONE: exporter lifecycle in the pipeline (`open`/`write`/`flush`/`aclose`,
  `durable_writes`, write for empty records), named tests `test_r9_*`,
  `test_r10_*`, `test_r20_*`–`test_r23_*` in `tests/semantics/test_run_rules.py`.
- DONE: `AsyncCsvExporter`, `AsyncJsonlExporter`, `read_jsonl_export`,
  `ExportError`; benchmark updated (`benchmarks/run_throughput.py`, exporters
  `discard`, `csv`, `jsonl`).
- DONE: claims 1 — `Claim`, `ClaimDraft` and drafts, `make_claim_id`,
  `locate_quote`, `sentence_bounds`, `AsyncClaimStore`, `InMemoryClaimStore`,
  `AsyncSqliteClaimStore`, `AsyncLLMClaimExtractor`, `AsyncClaimStoreExporter`,
  `ClaimError`, `ClaimStoreError`.
- DONE: stdlib logging in every module; `logger=`, `configure_logging`,
  `log_utils`, `_deprecation`, `AsyncETLPipeline.log` removed. Test helper
  `tests/log_capture.py` + autouse fixture in `tests/conftest.py`.
- DONE: removals — blocking ABCs, `Sync*Adapter`s, `LegacyExtractorAdapter`,
  `AsyncCsvUpsertExporter`, `AsyncSqlTableExporter`, `AsyncPlotly3DExporter`,
  `destination`. `ScatterPlotConfig` now exported from `sci_etl_core.processors`.
- DONE: extras and `load_env`; install-footprint tests.
- DONE: `tests/api/public_surface.txt` regenerated; `surface.py` stable list
  updated; `AsyncCsvUpsertExporter` and `configure_logging` removed from
  `tests/api/consumer_surface.txt` (regenerate with `scan_consumers.py` once
  both consumer ports are committed).
- DONE: bug found by the CLI suite and fixed: `AsyncCsvExporter` now creates
  the journal's parent folder (test `test_a_destination_in_a_new_folder_is_created`).
- DONE: docs — README, installation, quick start, blocking usage, configuration,
  `.env.example`, logging (rewritten), LLM caching, post-processing, shutdown,
  state, sources, search index, architecture, run semantics (R1–R23 table
  re-cited), reference pages (new `reference/claims.md`), new guides
  `guide/typed-entities.md` and `guide/claims.md`, `guide/sync-components.md`
  deleted, `mkdocs.yml` nav, SECURITY, CONTRIBUTING (component table, logging
  rule), ROADMAP (0.6.0 status, gate, two-minor deprecations, exit criterion),
  MIGRATION "Upgrading to 0.6", CHANGELOG `[Unreleased]` (code changes only).
  `tests/test_docs.py` passes; MIGRATION 0.6 examples were checked with the
  same checks.

## sci-etl-core: NOT DONE

- TODO: `docs/guide/migrating-a-pipeline.md` (the udg-catalogue walkthrough)
  still shows 0.5 code (`AsyncCsvUpsertExporter`, `destination=`, `logger=`,
  `configure_logging`). Update it after the udg-catalogue port is final, to
  mirror the real code. `tests/test_docs.py` currently passes on it only
  because its blocks aren't import-checked the same way; recheck.
- TODO: `SECURITY.md` supported-versions table says 0.5.x; update at release.
- TODO: `benchmarks/results/0.6.0.json` — rerun
  `python benchmarks/run_throughput.py` after reinstalling so the version
  reads 0.6.0; the measured ratios are recorded above.
- TODO: compat fixtures `tests/compat/v0_6_0/` (claim store, rejection store)
  can only be written from the tagged 0.6.0 release.
- TODO: `release-plan.md` and `claims-provenance-plan.md` Progress sections
  are not updated yet; mark Phase 3 and claims 0a/0b/1 DONE, with the
  decisions above.
- TODO: generate the patch series (see "Patches" below).

## sci-etl-cli (`../sci-etl-cli`): port to core 0.6 DONE, not committed

115 tests pass at 100% coverage against core master, ruff and mypy clean.
Version `0.4.0.dev0`, requires `sci-etl-core[config,async,arxiv,html,llm,pdf]>=0.6.0,<0.7`.

- DONE: `AsyncCsvExporter` (long format); `export.numeric_clip` and
  `export.normalizer` removed (fail validation); `record_id`/`extra` reserved
  column names; `ValidatingEntityExtractor` (`entity_filter.py`) deleted,
  validators combined with core `CompositeValidator` via `build_validator`;
  `run_logger` also routes the `sci_etl_core` logger; `logger=` arguments and
  `discard` removed; `validate` checks `yaml`, `httpx`, `bs4`, `lxml`,
  `openai`, `pdfplumber`; `llm.structured_output` wired; docs (README,
  index compatibility row 0.4.x ↔ 0.6, config-file, plugins, quick start);
  CHANGELOG `[Unreleased]`.
- NOTE: CLI CI installs core from PyPI, so CLI master CI stays red until core
  0.6.0 is published. Either commit the port on a branch until then, or accept
  the red build between the two releases.

## udg-catalogue (`../udg-catalogue`): port IN PROGRESS, not committed

Done in the working tree, **untested** (the session stopped while installing
astropy/streamlit into the scratch venv; udg's own `.venv` has core 0.4.0 and
was left untouched):

- `udg_catalogue/pipeline.py` rewritten: raw catalogue via
  `AsyncCsvExporter(paths.raw_catalogue, [galaxy_name, *MEASUREMENT_FIELDS])`;
  core `validator=GalaxyValidator` + `label_field` + `rejections=`
  `AsyncSqliteRejectionStore(paths.rejections)`; `ValidatedEntityExtractor`
  removed; indexing run uses a new `DiscardingExporter` (it must never write
  the catalogue, since `write(record, [])` would clear a paper's rows);
  no `logger=`/`destination=`.
- `udg_catalogue/validation.py`: `GalaxyValidator.validate()` returns
  `Violation`s (codes `no-name`, `paper-local-name`, `simulation-keyword`,
  `not-a-number`, `not-positive`, `out-of-range`, `no-measurement`);
  `rejection_reason` and `ValidatedEntityExtractor` removed.
- `udg_catalogue/postprocess.py`: new `RawRowsStep` (hides `record_id`/`extra`
  as `_record_id`/`_extra`, coerces measurements to numbers); dedup with
  `source_column="_record_id"`, `sources_column="source_papers"`;
  `source_papers` in `LEADING_COLUMNS`; `read_catalogue` dtypes.
- New `udg_catalogue/logs.py` (`configure_run_logging`, `PaperContextFilter`
  prefixing core lines with the paper id) and `udg_catalogue/manifest.py`
  (`write_manifest` → `data/run_manifest.json`: core/udg versions, model,
  base URL, prompt hashes, query, processed arXiv ids, row counts and SHA-256
  of both catalogues).
- `config.py`/`config.yaml`: `paths.rejections`, `paths.run_manifest`.
- `main.py`: `configure_run_logging`, `ShutdownSignal()`, writes the manifest
  after the catalogue. `app.py`: `configure_run_logging`.
- `literature.py`: `memory_ingestor(chunker)`, `searcher()`, `search()` lost
  their `logger` parameters.

TODO for udg-catalogue:

- Fix the tests: `tests/test_pipeline.py`, `test_validation.py` (uses
  `rejection_reason`, `ValidatedEntityExtractor`), `test_main.py` (patches
  `configure_logging`), `test_literature.py` (passes `print` to
  `memory_ingestor`), `test_postprocess.py` (raw CSV is now long format with
  `record_id`/`extra`), `test_app.py`, `test_published_catalogue.py`; add tests
  for `logs.py`, `manifest.py`, `RawRowsStep`, `DiscardingExporter`,
  `source_papers`. Keep 100% coverage.
- `requirements.txt`: `sci-etl-core[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]>=0.6.0,<0.7`;
  `requirements/local.txt` the same extras; drop `aiofiles` from
  `requirements/app.txt`.
- `.gitignore`: add `!data/run_manifest.json` so the manifest is committed.
- README/CONTRIBUTING: long-format raw catalogue, `source_papers`, rejection
  store and how to review it, manifest, logging.

## Step 8 (udg-catalogue rebuild and versioning): NOT DONE

Needs the user, because it costs money, deletes local data, and publishes:

1. Back up, then clear `data/llm_cache.db`, `data/processed_arxiv_ids.txt`,
   `data/pipeline_meta.json`, and `data/udg_database.csv` (all gitignored).
2. Run `python main.py --rescan` with `DEEPSEEK_API_KEY` set (about US$1.71
   per full rebuild at 2026-09-24 prices), then `--replace-catalogue` if the
   row-count guard refuses.
3. Remove the strict xfail markers in `tests/test_published_catalogue.py` for
   the rules the new catalogue passes.
4. Add `CHANGELOG.md` and `CITATION.cff` (version, date; DOI after Zenodo mints
   one), tag a release (for example `v1.0.0` of the catalog), enable the
   Zenodo GitHub integration to archive it and get the DOI.
5. Commit `data/udg_database_sorted.csv` and `data/run_manifest.json`.

## Step 9 (positioning text): NOT DONE

After step 8: update `README.md:12-18` and `docs/index.md:8-13` with the new
catalog count and DOI (currently "1,285 objects", which is stale), lead with
the result (pinned positioning rule), and point the docs landing page's
"See a complete project" card at `guide/migrating-a-pipeline.md` (the
udg-catalogue guide) instead of the repository, as ROADMAP v0.6.0 says.

## Step 10 (process): partly DONE

- DONE: `.devN` bump in core (`0.6.0.dev0`) and CLI (`0.4.0.dev0`);
  two-minor deprecation rule and release gate stated in ROADMAP.
- TODO: `.github/workflows/downstream.yml`: add a udg-catalogue job next to the
  CLI job (install core from the checkout with udg's extras, then udg without
  its pinned core, run `pytest -W error::DeprecationWarning`).
- TODO: `.github/workflows/release.yml`: make publishing `needs:` both
  downstream jobs (call `downstream.yml` via `workflow_call`, or duplicate the
  jobs), so a tag cannot publish unless both consumers pass.
- TODO: pin every `uses:` by commit SHA in all three repos (resolve with
  `git ls-remote https://github.com/actions/checkout refs/tags/v5` etc., keep
  the tag in a trailing `# v5` comment).
- TODO: CONTRIBUTING "Downstream tests" and a "Releasing" section: dev bump
  after each release, gate, two-minor deprecations; the local downstream
  install line needs `.[config,async,arxiv,html,llm,pdf]`.

## Patches (delivery format)

The consumer repos keep a `.patches/` series with one Conventional Commits
title per patch; core's `.patches/` holds the already-committed 0.5.1 series.
Snapshot trees were written with a temporary git index (the real index was
never touched). The tree objects may be garbage-collected eventually; if they
are gone, regenerate patches from the working trees instead.

| Snapshot | Tree | Contents |
|---|---|---|
| core T0 | `70a41d2874c1b2d1f1fb3fa06e3582ab5ab32159` | `HEAD` + version bump only |
| core T1 | `43ac800dfa25ad4154cedfeb9d7ff5055ac53b39` | + data contract and removals |
| core T2 | `57ca2f3a7fe5d1fd18130cbe3615f8b61f44c43f` | + claims package |
| core T3 | `86403b69f55bf43df012a244ce44a5bd30514ed8` | + stdlib logging |
| core T4 | `b7f8a944d1c9d3ad2a0e66dc6e4bd82142aae6c9` | + extras and `load_env` |
| CLI C0 | `c8f313582cacfecf9b891c903b48945534a20392` | CLI working tree with patches 01–06 |
| CLI C1 | `5e2a10ad5b54ecea45fd3205af003df99663357a` | + port to core 0.6 |
| udg U0 | `65667d1d52a91eeafc1587b8a1a56b43c4f0adec` | udg working tree with patches 01–09 |

Everything after T4 in core (docs, CSV journal folder fix, dedup sources) is
only in the working tree. Suggested core series and commit titles:

1. `chore: mark master as 0.6.0.dev0` (HEAD..T0)
2. `feat!: typed entities, validation reasons, and the exporter lifecycle` (T0..T1)
3. `feat: add claims and provenance (provisional)` (T1..T2)
4. `refactor!: log through the standard logging module` (T2..T3)
5. `build!: require only pydantic in the base install` (T3..T4)
6. `feat: record merged sources in DeduplicationStep; create the CSV journal folder` (T4..working tree, code only)
7. `docs: document the 0.6.0 data contract, claims, logging, and extras` (docs part of the rest)

CLI: `07-core-0.6.patch` — `feat!: run on sci-etl-core 0.6 with one CSV row per entity` (C0..C1).
udg-catalogue: `10-core-0.6.patch` — `feat!: port to sci-etl-core 0.6 with per-paper rows, rejection store, and run manifest` (U0..final).

Example: `git diff <old-tree> <new-tree> > .patches/NN-name.patch`, then add a
line to `.patches/SERIES`.
