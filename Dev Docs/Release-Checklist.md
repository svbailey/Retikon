# Release Checklist

- [x] All sprint exit criteria satisfied (Sprints 1-8).
- [x] `make lint` and `make test` pass in CI.
- [x] Load testing results recorded in `Dev Docs/Load-Testing.md`.
- [x] Snapshot refresh strategy approved.
- [x] Ops runbook reviewed.
- [x] Security checklist completed.
- [x] Dev Console validated end-to-end.
- [x] Release artifacts tagged and pushed.

## Notes

- Local `make lint` and `make test` run on 2026-01-26.
- CI run `main` workflow_dispatch passed (run `21362050792`, 2026-01-26).
- Dev Console deployed to `gs://retikon-dev-console-simitor-dev` with cache headers (2026-01-26).
- Release tags: `retikon-query:v2.5.0-rc1` (retagged to `realmodels-20260126-142604`), `retikon-ingest:v2.5.0-rc1`.
