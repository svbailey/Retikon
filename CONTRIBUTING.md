# Contributing to Retikon

Thank you for contributing to Retikon. This repo is the open-source Core of
Retikon, designed to be clean, reproducible, and easy to adopt.

## Ground rules

- Use the Retikon naming consistently (do not reintroduce "lattice").
- Keep changes small and scoped.
- Update docs when behavior or configuration changes.
- Keep diffs minimal; avoid reformatting unrelated code.

## Getting started

1) Read `AGENTS.md` for repo rules and defaults.
2) Review the current plan in `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`.
3) Use `Dev Docs/Local-Development.md` for local setup.

## Development workflow

- Create a feature branch from `main`.
- Add or update tests for new logic.
- Run unit tests locally:

```bash
pytest -q
```

- Ensure any config or schema changes are documented.

## Reporting issues

- Use GitHub issues with a minimal reproducible example.
- Include environment details and logs when possible.

## Pull requests

- Keep PRs focused and small.
- Summarize what changed and why.
- Note any risks, migration steps, or follow-up tasks.

## Code of Conduct

Please follow `CODE_OF_CONDUCT.md`.
