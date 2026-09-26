# Security Policy

We take the security of `sci-etl-core` and its users seriously. Thank you for
helping keep the project and its community safe.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.5.x   | ✅        |
| < 0.5   | ❌        |

Security fixes land on the latest minor release. Please upgrade before
reporting issues against older versions.

## Reporting a Vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately by email to **lanhua1122333@gmail.com** with:

- A description of the vulnerability and its potential impact.
- Steps to reproduce (proof-of-concept if possible).
- Affected version(s) and environment details.
- Any suggested remediation, if you have one.

### What to Expect

- **Acknowledgement** within 48 hours.
- An initial **assessment** within 5 business days.
- Coordinated disclosure: we'll agree on a timeline with you, ship a fix, and
  credit you in the release notes unless you prefer to remain anonymous.

Please give us reasonable time to remediate before any public disclosure.

## Secret Management

`sci-etl-core` is designed to keep credentials out of code, logs, and version
control:

- **`SecretStr` for API keys.**
  - `LLMConfig.api_key` is a Pydantic `SecretStr`, so keys don't appear in
    reprs, log lines, or tracebacks.
  - `AsyncOpenAICompatibleClient` and `AsyncOpenAIEmbedder` accept a
    `SecretStr` directly, and unwrap it only when they create the underlying
    client.
- **Environment-sourced secrets.**
  - `load_config` reads the key from an environment variable (`LLM_API_KEY` by
    default; configurable with `api_key_env_var`), optionally loaded from
    `.env`.
  - Variables already set in the environment take precedence over `.env`.
- **Keep keys out of YAML.** A set environment variable always overrides
  `llm.api_key` from the YAML file, which is only a fallback. A key committed
  in a config file is still a leak.
- **Config errors don't echo values.** `load_config`, `load_config_async`, and
  `validate_config` name each failing key and the reason, but never its value,
  and don't chain pydantic's error, which can contain the raw settings. YAML is
  parsed with `yaml.safe_load`.
- **Never commit `.env`.** Add `.env` to `.gitignore` and distribute a
  `.env.example` with placeholder values, as this repository does.
- **Database URLs are secrets too.** `SqlTableSink` receives its SQLAlchemy
  URL as a plain `url` string, as does the deprecated `AsyncSqlTableExporter`
  through `destination`. Build it from the environment at runtime, and don't
  log it.

## Data Handling

- **Stored text is unencrypted.**
  - `AsyncSqliteEmbeddingStore` and `AsyncSqliteFts5Store` persist full-text
    passages with their titles and source URLs.
  - `AsyncSqliteLLMResponseCache` persists model responses as JSON.
  - State files and state databases, which record the last error of each
    failed record, and CSV outputs are plain files.
  - If your corpus is licensed or sensitive, use filesystem permissions and
    encryption at rest.
- **CSV formula injection.** Keys come straight from LLM output.
  `AsyncCsvUpsertExporter` writes value columns as numbers, and by default
  prefixes an apostrophe to any key starting with `=`, `+`, `-`, `@`, a tab,
  or a carriage return, so spreadsheets don't evaluate it. Keep
  `escape_formulas` enabled for files people open in spreadsheet software.
  Other outputs — SQL tables from `SqlTableSink`, Plotly hover text from
  `Plotly3DSink`, and your own exporters and sinks — are not escaped.
- **No secrets in outputs.** Exporters write only the data they are given;
  scrub credential-bearing fields before export.

## Untrusted Input

- **Documents from third parties.**
  - PDF and LaTeX parsing runs on downloaded content.
  - LaTeX tarballs are read in memory (members are never extracted to disk).
    Download and decompressed sizes are unbounded by default, so a hostile file
    can exhaust memory.
  - Bound them: pass `max_download_bytes` to the extractors, which caps each
    response body after decoding, and `max_tex_bytes` to
    `LatexTarballParser`, which caps the TeX decompressed from one e-print. An
    oversized full-text download or e-print is logged and passed over.
  - PDF parsing is not bounded beyond the download size. Process large or
    untrusted corpora in a sandboxed, resource-limited environment.
- **Prompt injection.**
  - Paper text is sent to the LLM, and its content can steer the model's
    output.
  - Treat extracted entities as untrusted: validate them (for example with
    `NumericRangeValidator` and `KeywordExclusionValidator`) before downstream
    use.
- **Fail-open relevance filters.**
  - `AsyncLLMRelevanceFilter` and `AsyncEmbeddingRelevanceFilter` default to
    `default_on_error=True` and `default_on_empty_abstract=True`, so every
    record passes during an outage.
  - Set `default_on_error=False` if the filter acts as a control. The filter
    then fails closed: a failed call or an unclear verdict raises, so the
    record is neither extracted nor marked processed. The pipeline counts a
    failed attempt and retries the record on the next run.
  - `default_on_empty_abstract=False` marks every record without an abstract
    processed as irrelevant, permanently. Set it only when such records
    should never be extracted.
- **Model downloads.**
  - `AsyncSentenceTransformerEmbedder(model_name)` downloads model weights on
    first use.
  - Use a trusted, pinned model, or inject a preloaded `model=` built from
    weights you have vetted.

## Hardening Recommendations

- Rotate API keys regularly and scope them to least privilege.
- Pin dependencies and monitor advisories, especially for:
  - networking and LLM clients: `httpx`, `openai`
  - document, markup, and config parsing: `pdfplumber`, `beautifulsoup4`,
    `lxml`, `pyyaml`
  - data and numerics: `pandas`, `numpy`, `scikit-learn`
  - storage, plotting, and file IO: `SQLAlchemy`, `aiosqlite`, `plotly`,
    `aiofiles`
  - `sentence-transformers`, if installed
- Validate and sanitize any user-supplied query strings, file paths, and
  destinations before passing them to extractors or exporters.

## Scope

This policy covers the `sci-etl-core` codebase. Vulnerabilities in third-party
dependencies should be reported upstream, though we appreciate a heads-up so we
can pin or patch on our side.
