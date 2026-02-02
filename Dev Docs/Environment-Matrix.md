# Environment Matrix (v3.1)

This document locks the environment matrix for Retikon Pro. It captures
auth, control-plane storage, and operational toggles per environment.

## Environments

| Env | Project | Auth Issuer | Auth Audience | JWKS URI | Required Claims | Admin Roles/Groups | Gateway Userinfo | Control Plane Store | Collection Prefix | Read Mode | Write Mode | Fallback On Empty | Default Org/Site/Stream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| staging | simitor | https://securetoken.google.com/simitor | simitor | https://www.googleapis.com/service_accounts/v1/metadata/x509/securetoken@system.gserviceaccount.com | sub,iss,aud,exp,iat,org_id | admin / admins | true | firestore | staging_ | primary | single | false | simitor / "" / "" | JWT-only; gateway + service auth |
| dev | simitor | https://securetoken.google.com/simitor | simitor | https://www.googleapis.com/service_accounts/v1/metadata/x509/securetoken@system.gserviceaccount.com | sub,iss,aud,exp,iat,org_id | admin / admins | true | firestore | "" | primary | single | false | simitor / "" / "" | Optional local overrides |
| prod | N/A | N/A | N/A | N/A | sub,iss,aud,exp,iat,org_id | admin / admins | true | firestore | prod_ (TBD) | primary | single | false | org_id (TBD) | Not provisioned |

Source of truth:
- `infrastructure/terraform/terraform.tfvars.staging`
- `infrastructure/terraform/terraform.tfvars`

## Test Plan Owners

| Area | Owner | Notes |
| --- | --- | --- |
| Auth/JWT + Gateway | Simon Bailey (proposed) | JWT mint + gateway enforcement |
| Control Plane (Firestore) | Simon Bailey (proposed) | Schema, indexes, backfill |
| Ingestion | Simon Bailey (proposed) | Eventarc + idempotency |
| Query | Simon Bailey (proposed) | Snapshot + auth + search |
| RBAC/ABAC | Simon Bailey (proposed) | Enforcement coverage |
| Audit | Simon Bailey (proposed) | CRUD coverage + exports |
| Metering | Simon Bailey (proposed) | Usage event pipeline |
| Rate Limiting | Simon Bailey (proposed) | Redis backend |
| BYOC (k8s_adapter) | Simon Bailey (proposed) | Providers + smoke tests |
| Ops/Monitoring | Simon Bailey (proposed) | Alerts + runbooks |

## Cutover Dates (Proposed)

- Staging cutover: 2026-02-07
- Production cutover: 2026-03-07

## Verification Status (2026-02-02)

- Staging JWT env vars align with JWT-only and Firestore control-plane: verified from `terraform.tfvars.staging`.
- JWKS URL reachable and returns keys: verified.
- Required claims minted (org_id): verified (Firebase ID token includes org_id=simitor).
- End-to-end gateway JWT flow: verified (gateway `/query` returns 200; `/privacy/policies` returns 422 for missing body, indicating auth passed).

## Sign-off

- Scope confirmed by: Simon Bailey (proposed)
- Test plan owners confirmed by: Simon Bailey (proposed)
- Cutover dates confirmed by: Simon Bailey (proposed)

## Notes

- Required JWT claims are locked for v3.1.
- Use `CONTROL_PLANE_COLLECTION_PREFIX` to isolate environments.
