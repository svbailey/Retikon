# Security Checklist

## IAM and service accounts

- [ ] Ingestion, query, and index-builder service accounts are separate.
- [ ] Roles are least privilege for GCS and Firestore.
- [ ] Cloud Run services disallow unauthenticated access unless required.

## Secrets

- [ ] `QUERY_API_KEY` stored in Secret Manager for prod.
- [ ] Secret access limited to query service account.
- [ ] Rotation plan documented and tested.

## Network and data

- [ ] GCS buckets use uniform bucket-level access.
- [ ] Raw bucket lifecycle rule enabled.
- [ ] Graph bucket retention policy documented.

## Logging and audit

- [ ] JSON logging enabled for all services.
- [ ] Audit logs enabled for IAM and Secret Manager.
- [ ] DLQ access controlled.

## Dependencies

- [ ] Dependencies pinned in `requirements.txt`.
- [ ] Image builds are reproducible.
