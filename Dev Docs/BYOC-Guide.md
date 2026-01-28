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
- `RETIKON_SECRET_<NAME>` for secrets mounted as env vars
  - Example: `RETIKON_SECRET_API_KEY=...`

## Next steps (staging validation)

- Implement real provider bindings for your cluster
  (object store, queue, secrets, state store).
- Run the smoke test: `pytest tests/pro/test_k8s_adapter_smoke.py`.
- Deploy a BYOC environment and validate ingestion + query flows.
