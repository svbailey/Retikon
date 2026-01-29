# Core vs Pro Boundary (Monorepo)

This repo contains both Retikon Core (OSS) and Retikon Pro (commercial).
While we build in one repo, we enforce a strict boundary so Core can be
extracted to a public repo later with minimal change.

## Ownership

Core (OSS):
- retikon_core/
- local_adapter/
- retikon_cli/
- sdk/
- frontend/dev-console/
- tests/core/
- Dev Docs/openapi/retikon-core.yaml

Pro (Commercial):
- gcp_adapter/
- infrastructure/terraform/
- tests/pro/
- Dev Docs/pro/ (GCP deployment/runbooks)

## Dependency rules

Core:
- Must not import google.* or depend on GCP-specific SDKs.
- Default storage is local (filesystem).
- Optional object-store support is allowed in Core via extras (S3-compatible,
  GCS, Azure) but Core must remain cloud-agnostic and unmanaged.

Pro:
- May depend on GCP SDKs and adapters.
- Owns Cloud Run entrypoints, Eventarc, Firestore, Pub/Sub, Terraform.

## Storage + URI policy

- Core local mode returns file-backed URIs (file:// or absolute paths).
- When Core is configured with a remote object store, URIs preserve the
  storage scheme (gs://, s3://, etc.).
- Pro adds managed GCP storage, identity, and operational controls on top of
  the Core storage policy.

## Test boundaries

- Core tests live in tests/core and run with requirements-core.txt only.
- Pro tests live in tests/pro and run with requirements-pro.txt.
- CI enforces a boundary check to prevent GCP imports in Core.

## Release intent

- Core will be published as a public repo and PyPI package.
- Pro will depend on Core via a pinned package version.
