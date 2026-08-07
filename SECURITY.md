# Security Policy

We take the security of `sci-etl-core` and its users seriously. Thank you for
helping keep the project and its community safe.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |
| < 0.1   | ❌        |

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
- **Never commit `.env`.** Add `.env` to `.gitignore` and distribute a
  `.env.example` with placeholder values, as this repository does.
- **Database URLs are secrets too.** `AsyncSqlTableExporter` receives its
  SQLAlchemy URL as a plain `destination` string. Build it from the environment
  at runtime, and don't log it.

## Data Handling

- **Stored text is unencrypted.**
  - `AsyncSqliteEmbeddingStore` persists full-text passages with their titles
    and source URLs.
  - State files, state databases, and CSV outputs are plain files.
  - If your corpus is licensed or sensitive, use filesystem permissions and
    encryption at rest.
- **CSV formula injection.** Keys come straight from LLM output.
  `AsyncCsvUpsertExporter` writes value columns as numbers, and by default
  prefixes an apostrophe to any key starting with `=`, `+`, `-`, `@`, a tab,
  or a carriage return, so spreadsheets don't evaluate it. Keep
  `escape_formulas` enabled for files people open in spreadsheet software.
  Other outputs — SQL tables, Plotly hover text, and your own exporters — are
  not escaped.
- **No secrets in outputs.** Exporters write only the data they are given;
  scrub credential-bearing fields before export.

## Untrusted Input

- **Documents from third parties.**
  - PDF and LaTeX parsing runs on downloaded content.
  - LaTeX tarballs are read in memory (members are never extracted to disk),
    but download size, decompressed size, and PDF parsing are all unbounded, so
    a hostile file can exhaust memory or CPU.
  - Process large or untrusted corpora in a sandboxed, resource-limited
    environment.
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
  - Set both to `False` if the filter acts as a control.
- **Model downloads.**
  - `AsyncSentenceTransformerEmbedder(model_name)` downloads model weights on
    first use.
  - Use a trusted, pinned model, or inject a preloaded `model=` built from
    weights you have vetted.

## Hardening Recommendations

- Rotate API keys regularly and scope them to least privilege.
- Pin dependencies and monitor advisories, especially for:
  - networking and LLM clients: `httpx`, `openai`
  - document and markup parsing: `pdfplumber`, `beautifulsoup4`, `lxml`
  - data and numerics: `pandas`, `numpy`, `scikit-learn`
  - storage, plotting, and file IO: `SQLAlchemy`, `plotly`, `aiofiles`
  - `sentence-transformers`, if installed
- Validate and sanitize any user-supplied query strings, file paths, and
  destinations before passing them to extractors or exporters.

## Scope

This policy covers the `sci-etl-core` codebase. Vulnerabilities in third-party
dependencies should be reported upstream, though we appreciate a heads-up so we
can pin or patch on our side.
