# Firestore Control-Plane Schema (v3.1)

This document locks the Firestore control-plane schema used by Core/Pro
interfaces, adapters, and backfill tooling. It is additive only.

## Conventions

- Document IDs are UUIDv4 strings.
- Timestamps are ISO-8601 UTC strings (e.g. 2026-01-31T12:34:56Z).
- Required base fields on every control-plane document:
  - id
  - org_id
  - site_id (nullable)
  - stream_id (nullable)
  - status
  - created_at
  - updated_at
- status values are domain specific; default to active unless noted.
- Collection names are top-level and snake_case.
- Collection prefixes are optional; set `CONTROL_PLANE_COLLECTION_PREFIX`
  (e.g. `staging_`) to isolate environments within a shared Firestore project.
- Queries that span schema versions must use union_by_name=true when
  reading Parquet, but Firestore docs are forward-compatible.

## Collections

### rbac_bindings
Maps principals to roles (fallback when roles are not present in JWT).

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- principal_type (user|service|api_key)
- principal_id
- roles (array of strings)
- notes (string, optional)

### abac_policies
Attribute-based policies evaluated against JWT claims and request attributes.

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- effect (allow|deny)
- conditions (map<string, any>)
- description (string, optional)

### privacy_policies

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- name
- modalities (array)
- contexts (array)
- redaction_types (array)
- enabled (bool)

### fleet_devices

- id
- org_id
- site_id
- stream_id
- status (active|disabled|retired|unknown)
- created_at
- updated_at
- name
- tags (array)
- firmware_version (string, optional)
- last_seen_at (string, optional)
- metadata (map, optional)

### workflow_specs

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- name
- description (string, optional)
- schedule (string, optional)
- enabled (bool)
- steps (array of objects)

### workflow_runs

- id
- org_id
- site_id
- stream_id
- status (queued|running|completed|failed|canceled)
- created_at
- updated_at
- workflow_id
- started_at (string, optional)
- finished_at (string, optional)
- error (string, optional)
- output (map, optional)
- triggered_by (string, optional)

### chaos_policies

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- name
- description (string, optional)
- schedule (string, optional)
- enabled (bool)
- max_duration_minutes (int)
- max_percent_impact (int)
- steps (array of objects)

### chaos_runs

- id
- org_id
- site_id
- stream_id
- status (queued|running|completed|failed|canceled)
- created_at
- updated_at
- policy_id
- started_at (string, optional)
- finished_at (string, optional)
- error (string, optional)
- summary (map, optional)
- triggered_by (string, optional)

### webhook_registrations

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- name
- url
- secret (string, optional)
- event_types (array)
- enabled (bool)
- headers (map, optional)
- timeout_s (float, optional)

### alert_rules

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- name
- event_types (array)
- modalities (array)
- min_confidence (float, optional)
- tags (array)
- destinations (array of objects)
- enabled (bool)

### data_factory_models

- id
- org_id
- site_id
- stream_id
- status (active|deprecated|deleted)
- created_at
- updated_at
- name
- version
- description (string, optional)
- task (string, optional)
- framework (string, optional)
- tags (array)
- metrics (map, optional)

### data_factory_training_jobs

- id
- org_id
- site_id
- stream_id
- status (planned|queued|running|completed|failed|canceled)
- created_at
- updated_at
- dataset_id
- model_id
- epochs (int)
- batch_size (int)
- learning_rate (float)
- labels (array)
- started_at (string, optional)
- finished_at (string, optional)
- error (string, optional)
- output (map, optional)
- metrics (map, optional)

### ocr_connectors

- id
- org_id
- site_id
- stream_id
- status (active|disabled|deleted)
- created_at
- updated_at
- name
- url
- auth_type (none|header|bearer)
- auth_header (string, optional)
- token_env (string, optional)
- enabled (bool)
- is_default (bool)
- max_pages (int, optional)
- timeout_s (float, optional)
- notes (string, optional)

### api_keys

- id
- org_id
- site_id
- stream_id
- status (active|disabled|revoked)
- created_at
- updated_at
- name
- key_hash
- last_used_at (string, optional)
- scopes (array, optional)

## Composite indexes

Create the following composite indexes per collection (all ascending unless
noted). Single-field indexes are handled by Firestore defaults.

Base indexes for every collection:
- org_id, created_at (desc)
- org_id, status

Additional indexes by collection:
- workflow_runs: org_id, workflow_id, created_at (desc)
- workflow_runs: org_id, status, created_at (desc)
- chaos_runs: org_id, policy_id, created_at (desc)
- chaos_runs: org_id, status, created_at (desc)
- data_factory_training_jobs: org_id, status, created_at (desc)
- data_factory_training_jobs: org_id, model_id, created_at (desc)
- fleet_devices: org_id, status, updated_at (desc)
- fleet_devices: org_id, last_seen_at (desc)
- webhook_registrations: org_id, status, created_at (desc)
- ocr_connectors: org_id, enabled
- rbac_bindings: org_id, principal_id

## Backfill mapping (JSON -> Firestore)

Map each JSON control file to the matching Firestore collection:

- control/privacy_policies.json -> privacy_policies
- control/devices.json -> fleet_devices
- control/workflows.json -> workflow_specs
- control/workflow_runs.json -> workflow_runs
- control/chaos_policies.json -> chaos_policies
- control/chaos_runs.json -> chaos_runs
- control/webhooks.json -> webhook_registrations
- control/alerts.json -> alert_rules
- control/model_registry.json -> data_factory_models
- control/training_jobs.json -> data_factory_training_jobs
- control/ocr_connectors.json -> ocr_connectors
- control/rbac_bindings.json -> rbac_bindings
- control/abac_policies.json -> abac_policies

Backfill helper:
- `scripts/firestore_backfill.py` (supports `--base-uri`, `--collection-prefix`,
  `--dry-run`, and per-domain flags).
