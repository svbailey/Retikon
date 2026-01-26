#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
ENV="${ENV:-dev}"
JOB_NAME="${JOB_NAME:-retikon-index-builder-${ENV}}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is required (or set a default with gcloud config)." >&2
  exit 1
fi

echo "Executing Cloud Run job: ${JOB_NAME} (project=${PROJECT_ID}, region=${REGION})"
gcloud run jobs execute "${JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --wait
