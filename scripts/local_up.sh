#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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
