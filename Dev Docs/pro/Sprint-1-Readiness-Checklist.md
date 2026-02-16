# Sprint 1 Readiness Checklist (v3.05)

This checklist tracks required preconditions before Sprint 1 implementation
starts. It is derived from:

- `Dev Docs/pro/Sprint-Plan-v3.05.md`
- `Dev Docs/pro/Parity-API-Contract-v1.md`

## Readiness gates

- [x] Sprint 0 acceptance evidence is recorded.
  - Source: `tests/fixtures/eval/results-20260216-123153.json`
  - Metrics: `recall@10=1.0`, `recall@50=1.0`, `MRR@10=1.0`
- [x] Parity contract v1 exists and is implementation baseline.
  - Source: `Dev Docs/pro/Parity-API-Contract-v1.md`
- [x] Search contract details are explicit:
  - FilterSpec v1
  - deterministic cursor pagination
  - grouping response shape
  - mode/modality precedence
- [x] Typed error contract is defined in parity contract.
- [x] Sprint 1 kill-switch/default env vars are defined in code + IaC.
  - Code: `retikon_core/services/query_config.py`
  - IaC: `infrastructure/terraform/variables.tf`,
    `infrastructure/terraform/main.tf`,
    `infrastructure/terraform/terraform.tfvars.example`
- [x] Query service environment reference is updated.
  - Source: `Dev Docs/Environment-Reference.md`
- [x] Sprint 1 test matrix is documented.
  - Source: `Dev Docs/pro/Sprint-1-Test-Matrix.md`

## Manual sign-off

- Engineering lead: ____________________  Date: __________
- Product/API owner: ___________________  Date: __________
- Ops/SRE owner: _______________________  Date: __________
