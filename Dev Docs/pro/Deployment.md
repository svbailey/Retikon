# Deployment

Pro only. This runbook applies to Retikon Pro (GCP).

This assumes Terraform-managed infrastructure and Cloud Run services.

For BYOC (Kubernetes) deployments, see `Dev Docs/BYOC-Guide.md`.

## Ingress policy (ingestion)

- Prod: keep ingestion service ingress as `internal-and-cloud-load-balancing`.
- Staging: allow ingress `all` for Tier-3 HTTP tests only.

## Build images

```bash
make build-ingest
make build-query
make build-audit
make build-data-factory
make build-privacy
```

If you build the Dev Console UI, set:

- `VITE_AUDIT_URL` to the audit service base URL.
- `VITE_DATA_FACTORY_URL` to the data factory service base URL.
- `VITE_PRIVACY_URL` to the privacy service base URL.

Tag and push to Artifact Registry (example):

```bash
docker tag retikon-ingest:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG

docker tag retikon-query:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG

docker tag retikon-audit:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-audit:TAG

docker tag retikon-data-factory:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-data-factory:TAG

docker tag retikon-privacy:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-privacy:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-audit:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-data-factory:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-privacy:TAG
```

## Terraform apply

```bash
cd infrastructure/terraform
terraform init
terraform apply \
  -var="ingest_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG" \
  -var="query_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG" \
  -var="audit_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-audit:TAG" \
  -var="data_factory_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-data-factory:TAG" \
  -var="privacy_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-privacy:TAG"
```

## Post-deploy

- Verify `/health` responses for ingestion, query, audit, data factory, and privacy.
- Confirm snapshot load logs at query startup.
- Run smoke queries via curl or the Dev Console.

## Audit service configuration

- `AUDIT_API_KEY` defaults to the same Secret Manager key as `QUERY_API_KEY`.
- `AUDIT_REQUIRE_ADMIN=1` in prod (enforced by Terraform variable
  `audit_require_admin`).

## OCR connector setup (Pro)

OCR connectors are configured via the Data Factory service and stored in the
graph control namespace.

1) Register a connector (example):

```bash
curl -X POST "$DATA_FACTORY_URL/data-factory/ocr/connectors" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DATA_FACTORY_API_KEY" \
  -d '{
    "name": "OCR Primary",
    "url": "https://ocr.example.com/v1/extract",
    "auth_type": "header",
    "auth_header": "X-API-Key",
    "token_env": "OCR_API_KEY",
    "enabled": true,
    "is_default": true,
    "max_pages": 5,
    "timeout_s": 30
  }'
```

2) Configure ingestion to use OCR:

- `ENABLE_OCR=1`
- `OCR_MAX_PAGES=5` (optional)
- `OCR_CONNECTOR_ID=<connector-id>` (optional if a single default exists)
- Set the token value for the chosen connector:
  - `OCR_API_KEY=<secret>` (or whatever `token_env` is set to)

Notes:
- If multiple enabled connectors exist and no default is set, ingestion will
  error until `OCR_CONNECTOR_ID` is provided.

## Office conversion setup (Pro)

Office conversion is handled by the Data Factory service.

Inline mode (simple):
- `OFFICE_CONVERSION_MODE=inline`
- `OFFICE_CONVERSION_BACKEND=libreoffice`
- Ensure LibreOffice is available in the container (`soffice` on PATH or
  set `LIBREOFFICE_BIN=/path/to/soffice`)

Queue mode (async):
- `OFFICE_CONVERSION_MODE=queue`
- `OFFICE_CONVERSION_TOPIC=projects/$PROJECT/topics/retikon-office-conversion`
- `OFFICE_CONVERSION_DLQ_TOPIC=projects/$PROJECT/topics/retikon-office-conversion-dlq`
- Configure Pub/Sub push to call:
  - `POST /data-factory/convert-office/worker`

Optional limits:
- `OFFICE_CONVERSION_MAX_BYTES` to cap payload size (defaults to `MAX_RAW_BYTES`).
