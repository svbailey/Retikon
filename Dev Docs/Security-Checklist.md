# Security Checklist

## IAM and service accounts

- [x] Ingestion, query, and index-builder service accounts are separate.
- [x] Roles are least privilege for GCS and Firestore.
- [x] Cloud Run services disallow unauthenticated access unless required.

## Secrets

- [x] `QUERY_API_KEY` stored in Secret Manager for prod.
- [x] Secret access limited to query service account.
- [x] Rotation plan documented and tested.

## Network and data

- [x] GCS buckets use uniform bucket-level access.
- [x] Raw bucket lifecycle rule enabled.
- [x] Graph bucket retention policy documented.

## Logging and audit

- [x] JSON logging enabled for all services.
- [x] Audit logs enabled for IAM and Secret Manager.
- [x] DLQ access controlled.

## Dependencies

- [x] Dependencies pinned in `requirements.txt`.
- [x] Image builds are reproducible.
