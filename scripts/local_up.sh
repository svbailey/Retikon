#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ROOT_DIR}/.env"
ENV_EXAMPLE="${ROOT_DIR}/.env.example"
ENV_LOCAL="${ROOT_DIR}/.env.local"

if [ ! -f "$ENV_FILE" ] && [ -f "$ENV_EXAMPLE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "Created .env from .env.example; please review values." >&2
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

if [ -f "$ENV_LOCAL" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_LOCAL"
  set +a
fi

: "${STORAGE_BACKEND:=local}"
: "${ENV:=dev}"
: "${LOG_LEVEL:=INFO}"
: "${MAX_RAW_BYTES:=500000000}"
: "${MAX_VIDEO_SECONDS:=300}"
: "${MAX_AUDIO_SECONDS:=1200}"
: "${MAX_FRAMES_PER_VIDEO:=900}"
: "${CHUNK_TARGET_TOKENS:=512}"
: "${CHUNK_OVERLAP_TOKENS:=50}"
: "${GRAPH_PREFIX:=retikon_v2}"

export STORAGE_BACKEND ENV LOG_LEVEL MAX_RAW_BYTES MAX_VIDEO_SECONDS MAX_AUDIO_SECONDS
export MAX_FRAMES_PER_VIDEO CHUNK_TARGET_TOKENS CHUNK_OVERLAP_TOKENS GRAPH_PREFIX

if [ "${STORAGE_BACKEND}" = "local" ]; then
  : "${LOCAL_GRAPH_ROOT:=${ROOT_DIR}/retikon_data/graph}"
  : "${SNAPSHOT_URI:=${LOCAL_GRAPH_ROOT}/snapshots/retikon.duckdb}"
  export LOCAL_GRAPH_ROOT SNAPSHOT_URI
  mkdir -p "${LOCAL_GRAPH_ROOT}"
  if [ ! -f "${SNAPSHOT_URI}" ]; then
    echo "Snapshot not found. Bootstrapping local snapshot..." >&2
    "${PYTHON:-python}" -m retikon_cli.cli init --env-file "${ENV_FILE}" --example-file "${ENV_EXAMPLE}" --no-seed --force-snapshot
  fi
else
  missing=()
  if [ -z "${RAW_BUCKET:-}" ]; then
    missing+=("RAW_BUCKET")
  fi
  if [ -z "${GRAPH_BUCKET:-}" ]; then
    missing+=("GRAPH_BUCKET")
  fi
  if [ -z "${GRAPH_PREFIX:-}" ]; then
    missing+=("GRAPH_PREFIX")
  fi
  if [ "${#missing[@]}" -ne 0 ]; then
    echo "Missing required env vars for STORAGE_BACKEND=gcs: ${missing[*]}" >&2
    exit 1
  fi
fi

HOST="${RETIKON_HOST:-0.0.0.0}"
INGEST_PORT="${RETIKON_INGEST_PORT:-8081}"
QUERY_PORT="${RETIKON_QUERY_PORT:-8082}"
LOG_LEVEL="${RETIKON_LOG_LEVEL:-info}"

uvicorn local_adapter.ingestion_service:app --host "$HOST" --port "$INGEST_PORT" --log-level "$LOG_LEVEL" &
INGEST_PID=$!

uvicorn local_adapter.query_service:app --host "$HOST" --port "$QUERY_PORT" --log-level "$LOG_LEVEL" &
QUERY_PID=$!

trap 'kill "$INGEST_PID" "$QUERY_PID"' INT TERM

wait "$INGEST_PID" "$QUERY_PID"
