# Deployment

Pro only. This runbook applies to Retikon Pro (GCP).

This assumes Terraform-managed infrastructure and Cloud Run services.

## Ingress policy (ingestion)

- Prod: keep ingestion service ingress as `internal-and-cloud-load-balancing`.
- Staging: allow ingress `all` for Tier-3 HTTP tests only.

## Build images

```bash
make build-ingest
make build-query
make build-audit
```

If you build the Dev Console UI, set:

- `VITE_AUDIT_URL` to the audit service base URL.

Tag and push to Artifact Registry (example):

```bash
docker tag retikon-ingest:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG

docker tag retikon-query:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG

docker tag retikon-audit:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-audit:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-audit:TAG
```

## Terraform apply

```bash
cd infrastructure/terraform
terraform init
terraform apply \
  -var="ingest_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG" \
  -var="query_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG" \
  -var="audit_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-audit:TAG"
```

## Post-deploy

- Verify `/health` responses for ingestion, query, and audit.
- Confirm snapshot load logs at query startup.
- Run smoke queries via curl or the Dev Console.

## Audit service configuration

- `AUDIT_API_KEY` defaults to the same Secret Manager key as `QUERY_API_KEY`.
- `AUDIT_REQUIRE_ADMIN=1` in prod (enforced by Terraform variable
  `audit_require_admin`).
