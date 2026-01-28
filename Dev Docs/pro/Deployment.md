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
