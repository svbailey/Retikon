# Retikon DLQ Runbook

## Overview

The ingestion service publishes failed events to the DLQ Pub/Sub topic. Use the
DLQ tool to inspect and replay messages safely.

## Prerequisites

- `gcloud auth login` and `gcloud config set project <project-id>`
- Pub/Sub permissions for the DLQ subscription.

## List Messages (Peek)

```bash
python scripts/dlq_tool.py \
  --project simitor \
  --subscription retikon-ingest-dlq-sub \
  list --limit 10
```

## Pull Full Payload

```bash
python scripts/dlq_tool.py \
  --project simitor \
  --subscription retikon-ingest-dlq-sub \
  pull --limit 1
```

Add `--ack` to remove the pulled messages.

## Replay to Ingestion

```bash
python scripts/dlq_tool.py \
  --project simitor \
  --subscription retikon-ingest-dlq-sub \
  replay --limit 1 \
  --ingest-url https://retikon-ingestion-dev-yt27ougp4q-uc.a.run.app/ingest
```

Add `--ack` to remove replayed messages from the DLQ subscription.

## Notes

- DLQ messages include the original CloudEvent payload and error metadata.
- Replayed events are sent to `/ingest` as JSON CloudEvents.
