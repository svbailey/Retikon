#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-simitor}"

create_index() {
  local collection="$1"
  shift
  local output
  if ! output=$(gcloud firestore indexes composite create \
    --project "${PROJECT_ID}" \
    --collection-group "${collection}" \
    "$@" \
    --async 2>&1); then
    if [[ "${output}" == *"ALREADY_EXISTS"* ]]; then
      echo "Index already exists: ${collection} $*"
      return 0
    fi
    echo "${output}" >&2
    return 1
  fi
  echo "${output}"
}

collections=(
  rbac_bindings
  abac_policies
  privacy_policies
  fleet_devices
  workflow_specs
  workflow_runs
  chaos_policies
  chaos_runs
  webhook_registrations
  alert_rules
  data_factory_models
  data_factory_training_jobs
  ocr_connectors
  api_keys
)

# Base indexes for every collection.
for collection in "${collections[@]}"; do
  create_index "${collection}" \
    --field-config=field-path=org_id,order=ascending \
    --field-config=field-path=created_at,order=descending
  create_index "${collection}" \
    --field-config=field-path=org_id,order=ascending \
    --field-config=field-path=status,order=ascending
done

# Additional indexes by collection.
create_index workflow_runs \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=workflow_id,order=ascending \
  --field-config=field-path=created_at,order=descending
create_index workflow_runs \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=created_at,order=descending

create_index chaos_runs \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=policy_id,order=ascending \
  --field-config=field-path=created_at,order=descending
create_index chaos_runs \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=created_at,order=descending

create_index data_factory_training_jobs \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=created_at,order=descending
create_index data_factory_training_jobs \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=model_id,order=ascending \
  --field-config=field-path=created_at,order=descending

create_index fleet_devices \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=updated_at,order=descending
create_index fleet_devices \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=last_seen_at,order=descending

create_index webhook_registrations \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=created_at,order=descending

create_index ocr_connectors \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=enabled,order=ascending

create_index rbac_bindings \
  --field-config=field-path=org_id,order=ascending \
  --field-config=field-path=principal_id,order=ascending

gcloud firestore indexes composite list --project "${PROJECT_ID}"
