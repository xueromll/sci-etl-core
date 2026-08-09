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

- **`SecretStr` for API keys.** `LLMConfig.api_key` is a Pydantic `SecretStr`,
  so keys don't appear in reprs, log lines, or tracebacks. Unwrap only at the
  point of use.
- **Environment-sourced secrets.** `load_config` reads the key from an
  environment variable (`LLM_API_KEY` by default) via `.env`; it is never
  required in the YAML file.
- **Never commit `.env`.** Add it to `.gitignore` and distribute a
  `.env.example` with placeholder values instead.
- **No secrets in structured output.** Exporters write only extracted data;
  scrub any credential-bearing fields before export.

### Hardening Recommendations

- Rotate API keys regularly and scope them to least privilege.
- Pin dependencies and monitor advisories for `httpx`, `openai`, `pandas`,
  `pdfplumber`, and other transitive packages.
- Validate and sanitize any user-supplied query strings, file paths, and
  destinations before passing them to extractors or exporters.
- Run untrusted document parsing (PDF/LaTeX) in a sandboxed environment.

## Scope

This policy covers the `sci-etl-core` codebase. Vulnerabilities in third-party
dependencies should be reported upstream, though we appreciate a heads-up so we
can pin or patch on our side.
