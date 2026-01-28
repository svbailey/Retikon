# Deployment

Pro only. This runbook applies to Retikon Pro (GCP).

This assumes Terraform-managed infrastructure and Cloud Run services.

## Build images

```bash
make build-ingest
make build-query
```

Tag and push to Artifact Registry (example):

```bash
docker tag retikon-ingest:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG

docker tag retikon-query:dev \
  $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG

docker push $REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG
```

## Terraform apply

```bash
cd infrastructure/terraform
terraform init
terraform apply \
  -var="ingest_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-ingest:TAG" \
  -var="query_image=$REGION-docker.pkg.dev/$PROJECT/retikon/retikon-query:TAG"
```

## Post-deploy

- Verify `/health` responses for ingestion and query.
- Confirm snapshot load logs at query startup.
- Run smoke queries via curl or the Dev Console.
