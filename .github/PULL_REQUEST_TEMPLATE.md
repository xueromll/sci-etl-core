## Summary

What does this PR do and why? Keep it focused on a single logical change.

Closes #

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no behavior change)
- [ ] Documentation
- [ ] Tests / tooling

## Checklist

- [ ] Tests added or updated for the change
- [ ] Coverage stays at 100% (`pytest --cov=sci_etl_core` fails otherwise)
- [ ] Async conventions followed (no sync twins, blocking work off the event
      loop, `CancelledError` re-raised, failures signaled with library
      exceptions)
- [ ] New ABC implementations added to `tests/contract/`
- [ ] Type hints on all public signatures (`mypy` / `ruff` clean if you use them)
- [ ] PEP 8 naming; American English identifiers and docstrings
- [ ] No domain-specific constants added to the core
- [ ] Public API changes reflected in the relevant `__init__.py` and `__all__`
- [ ] Docs updated (README / MIGRATION / ROADMAP) if user-facing

## How Was This Tested?

Describe the tests you ran and any relevant configuration.

## Notes for Reviewers

Anything you'd like reviewers to focus on, trade-offs made, or follow-ups
deferred to a later PR.
