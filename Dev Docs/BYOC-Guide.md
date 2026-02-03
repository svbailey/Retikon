# BYOC Guide (Kubernetes)

Pro only. This guide describes a Bring-Your-Own-Cluster (BYOC) deployment for
Retikon Pro using the Kubernetes adapter.

## Scope

- Core provides provider interfaces in `retikon_core/providers/`.
- Pro implements Kubernetes adapter wiring in `k8s_adapter/`.

## Provider interfaces (Core)

The BYOC adapter expects implementations for:

- Object store (read/write/list)
- Queue (publish/pull)
- Secrets store (read)
- State store (get/set/delete)

These interfaces live in `retikon_core/providers/` and are intentionally
cloud-agnostic.

## Kubernetes adapter (Pro)

The BYOC adapter entrypoint is `k8s_adapter.K8sAdapter`. The initial
implementation is a minimal wiring layer that loads configuration from
environment variables and binds provider implementations.

### Environment variables

- `K8S_NAMESPACE` (default: `default`)
- `K8S_OBJECT_STORE_BACKEND` (`fsspec` recommended)
- `K8S_OBJECT_STORE_URI` (e.g., `file:///data/retikon`, `s3://bucket/prefix`)
- `K8S_QUEUE_BACKEND` (`redis|memory`)
- `K8S_QUEUE_PREFIX` (optional; defaults to `retikon`)
- `K8S_SECRETS_BACKEND` (`file|env|chain`)
- `K8S_SECRETS_DIR` (defaults to `/var/run/secrets/retikon`)
- `K8S_STATE_BACKEND` (`redis|file|memory`)
- `K8S_STATE_DIR` (file backend; defaults to `/var/run/retikon/state`)
- `K8S_STATE_PREFIX` (optional; defaults to `retikon`)
- `K8S_REDIS_URL` or `K8S_REDIS_HOST`/`K8S_REDIS_PORT`/`K8S_REDIS_DB`/`K8S_REDIS_PASSWORD`/`K8S_REDIS_SSL`
  (used for queue/state backends when `redis` is selected)
- `RETIKON_SECRET_<NAME>` for secrets mounted as env vars
  - Example: `RETIKON_SECRET_AUTH_TOKEN=...`

## Next steps (staging validation)

- Implement real provider bindings for your cluster
  (object store, queue, secrets, state store).
- Run the smoke test: `pytest tests/pro/test_k8s_adapter_smoke.py`.
- Deploy a BYOC environment and validate ingestion + query flows.
