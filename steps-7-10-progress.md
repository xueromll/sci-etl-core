# Steps 7–10 of `audit-analysis.md`: progress handoff

Written 2026-09-26 and updated 2026-09-27. Core's 0.6 work is committed as
`9327cb3`; the changes of 2026-09-27 and both consumer ports sit in the
working trees. This file is untracked; add
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

## sci-etl-core: done on 2026-09-27, not committed

- DONE: `AsyncCsvExporter` no longer escapes plain numbers. It wrote
  `dec=-5.361` as `'-5.361`, so pandas read every southern declination in
  udg-catalogue's raw catalogue (and any negative number in a CLI CSV) as
  text. Tests in `tests/async/test_csv_async.py`; CHANGELOG, post-processing
  guide, SECURITY updated. Suite: 2,564 tests at 100%, ruff and mypy clean,
  `mkdocs build --strict` clean.
- DONE: `docs/guide/migrating-a-pipeline.md` — "Where you'll end up" shows the
  0.6 code, the mapping table names 0.6 components, and "Upgrading the
  project" gained "Moving to 0.5" and "Moving to 0.6".
- DONE: `release-plan.md` and `claims-provenance-plan.md` Progress sections.
- DONE: step 10 workflows — `downstream.yml` has a `catalogue` job and
  `workflow_call`; both jobs read the extras from the consumer's own
  requirement; `release.yml` builds only after `tests` and `downstream`; every
  `uses:` in all three repos is pinned by SHA with the tag in a comment.
  CONTRIBUTING: downstream commands for both consumers and a "Releasing"
  section. ROADMAP consumer table updated.
- Suggested commit titles:
  1. `fix: write plain numbers unescaped in AsyncCsvExporter`
  2. `ci: gate releases on the sci-etl-cli and udg-catalogue suites and pin actions by SHA`
  3. `docs: bring the udg-catalogue guide to 0.6 and document releasing`

## sci-etl-core: NOT DONE

- TODO: `SECURITY.md` supported-versions table says 0.5.x; update at release.
- TODO: `benchmarks/results/0.6.0.json` — rerun
  `python benchmarks/run_throughput.py` after reinstalling so the version
  reads 0.6.0.
- TODO: compat fixtures `tests/compat/v0_6_0/` (claim store, rejection store)
  can only be written from the tagged 0.6.0 release.
- NOTE: the Downstream workflow stays red on core `master` until both
  consumer ports reach their default branches, and CLI CI stays red until
  core 0.6.0 is on PyPI (it installs core from PyPI).

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

## udg-catalogue (`../udg-catalogue`): port DONE, not committed

209 tests pass at 100% coverage, `-W error::DeprecationWarning` clean
(scratch venv, Python 3.14, with astropy and streamlit).

- DONE: pipeline on `AsyncCsvExporter` (long format), core validator with
  `label_field` and `AsyncSqliteRejectionStore`, `DiscardingExporter` for the
  indexing run, `GalaxyValidator.validate` with rule codes, `RawRowsStep`,
  `source_papers`, `logs.py`, `manifest.py`, `ShutdownSignal` in `main.py`.
- DONE: post-processing refuses a raw catalogue without `record_id` (the 0.5
  wide format) and says to rebuild with `--rescan`.
- DONE: tests fixed and added (`test_logs.py`, `test_manifest.py`,
  `RawRowsStep`, rejection store, negative coordinates round trip).
- DONE: `requirements.txt` and `requirements/local.txt` on
  `[config,async,arxiv,html,llm,pdf,processors,cluster,embeddings,embeddings-local,search]>=0.6.0,<0.7`;
  `aiofiles` dropped from `requirements/app.txt`; `.gitignore` keeps
  `data/run_manifest.json`.
- DONE: README (long-format raw catalogue, `source_papers`, rejection store
  with a review example, manifest, logs, rebuild notes) and CONTRIBUTING.
- The README "Results at a Glance" numbers and its `sci-etl-core 0.5` row
  describe the committed catalogue; refresh them after the step 8 rebuild.

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

## Step 10 (process): DONE in the working trees

- DONE: `.devN` bump in core (`0.6.0.dev0`) and CLI (`0.4.0.dev0`);
  two-minor deprecation rule and release gate stated in ROADMAP.
- DONE: udg-catalogue job in `downstream.yml`; `release.yml` needs both
  downstream jobs; actions pinned by SHA in all three repos; CONTRIBUTING
  "Downstream tests" and "Releasing".

## Patches (delivery format)

Core's 0.6 work was committed directly (`9327cb3`), so core needs no patch
series; commit the working tree with the titles above. The consumer series
are written:

| Repo | Patch | Title |
|---|---|---|
| sci-etl-cli | `07-core-0.6.patch` | `feat!: run on sci-etl-core 0.6 with one CSV row per entity` |
| sci-etl-cli | `08-pin-actions.patch` | `ci: pin GitHub Actions to commit SHAs` |
| udg-catalogue | `10-core-0.6.patch` | `feat!: port to sci-etl-core 0.6 with per-paper rows, rejection store, and run manifest` |
| udg-catalogue | `11-pin-actions.patch` | `ci: pin GitHub Actions to commit SHAs` |

Each series starts from the repository's `HEAD`; patches 01–06 (CLI) and
01–09 (udg-catalogue) come first.
