# Release Checklist

## v3.0 (Draft)

- [ ] All sprint exit criteria satisfied (Sprints 1-10).
- [ ] `python -m ruff check .` and `python -m pytest -q` pass in CI.
- [x] Load testing results recorded in `Dev Docs/Load-Testing.md` (query + ingest + streaming + compaction).
- [ ] Multi-tenant API key registry created and validated.
- [x] Metering events recorded to `UsageEvent` GraphAr vertex.
- [ ] Snapshot refresh strategy approved.
- [x] Ops runbook reviewed.
- [x] Security checklist completed.
- [x] Dev Console validated end-to-end.
- [ ] Release artifacts tagged and pushed.

## v2.5 (Complete)

- [x] All sprint exit criteria satisfied (Sprints 1-8).
- [x] `make lint` and `make test` pass in CI.
- [x] Load testing results recorded in `Dev Docs/Load-Testing.md`.
- [x] Release notes published in `Dev Docs/Release-Notes-v2.5.md`.
- [x] Snapshot refresh strategy approved.
- [x] Ops runbook reviewed.
- [x] Security checklist completed.
- [x] Dev Console validated end-to-end.
- [x] Release artifacts tagged and pushed.

## Notes

- Local `make lint` and `make test` run on 2026-01-26.
- Local `python -m ruff check .` and `python -m pytest -q` run on 2026-01-27 (CI pending).
- CI run `main` workflow_dispatch passed (run `21362050792`, 2026-01-26).
- CI run `ci` workflow_dispatch queued (run `21408326726`, 2026-01-27).
- Dev Console deployed to `gs://retikon-dev-console-simitor-dev` with cache headers (2026-01-26).
- Release tags: `retikon-query:v2.5.0-rc1` (retagged to `realmodels-20260126-142604`), `retikon-ingest:v2.5.0-rc1`.
- Dev Console E2E validation (2026-01-27): `/health` 200, `/dev/snapshot-status` 200, `/dev/index-status` 200, `/dev/manifest` 200, `/dev/parquet-preview` 200 (UsageEvent preview).
- Metering evidence (2026-01-27): `UsageEvent` written to `gs://retikon-graph-simitor-dev/retikon_v2/vertices/UsageEvent/core/part-2accc6c0-1e59-4703-a27e-a7891b5391f6.parquet` with org/site/stream scope.
- API key registry created at `gs://retikon-graph-simitor-dev/retikon_v2/control/api_keys.json`; registry-backed keys currently return 401 on query service (needs investigation).
- Dev Cloud Run config updated manually (2026-01-27): set `METERING_ENABLED=1` on `retikon-query-dev` and `retikon-ingestion-dev`; set `API_KEY_REGISTRY_URI` on `retikon-query-dev` (Terraform not yet updated).
