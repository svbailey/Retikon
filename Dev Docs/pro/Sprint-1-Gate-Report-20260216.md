# Sprint 1 Gate Report (2026-02-16)

## Scope

Post-implementation production gates required before Sprint 2:

1. Clean staging A/B retrieval eval (`RERANK_ENABLED=0` vs `1`)
2. Staging Search contract smoke (`group_by`, pagination cursor, typed errors)
3. Staging env rollout audit for Sprint 1 query/rerank/fusion flags

## Rollout executed

- Built and deployed tuned Sprint 1 query image:
  - `us-central1-docker.pkg.dev/simitor/retikon-repo/retikon-query:sprint1-latency-20260216-163425`
- Applied Terraform staging rollout for Sprint 1 tuning/env updates (`google_cloud_run_service.query` target):
  - rerank timeout wiring (`MODEL_INFERENCE_RERANK_TIMEOUT_S`)
  - reduced rerank workload defaults (`TOP_N/BATCH/TOKENS`)
  - rerank caps (`RERANK_MIN_CANDIDATES`, `RERANK_MAX_TOTAL_CHARS`)
  - confidence-gap skip disabled by default (`RERANK_SKIP_SCORE_GAP=1.0`)
- Re-ran staging A/B and contract smoke using fresh Firebase auth token.

## Final gate artifacts (post-tuning rerun)

- A/B eval:
  - `tests/fixtures/eval/results-sprint1-staging-rerank-off-20260216-181118.json`
  - `tests/fixtures/eval/results-sprint1-staging-rerank-on-20260216-184720.json`
  - `tests/fixtures/eval/results-sprint1-staging-rerank-diff-20260216-184730.json`
- API smoke:
  - `tests/fixtures/eval/sprint1-staging-api-smoke-20260216-184415.json`
- Env audit:
  - `tests/fixtures/eval/sprint1-staging-env-audit-20260216-182536.json`

## Gate results (post-tuning rerun)

### 1) Staging A/B eval

- Quality:
  - `recall@10`: unchanged (`1.0 -> 1.0`)
  - `recall@50`: unchanged (`1.0 -> 1.0`)
  - `top_k_overlap`: unchanged (`1.0 -> 1.0`)
  - `MRR@10`: improved (`0.7857 -> 1.0`, delta `+0.2143`)
- Latency:
  - mean latency improved from `2238.91ms` to `2168.02ms` (delta `-70.89ms`)

Interpretation:
- Rerank now improves ordering quality while staying latency-neutral in staging.

### 2) Staging API contract smoke

- `basic_query_200`: pass
- `response_has_meta`: pass
- `grouping_present`: pass
- `next_page_token_present`: pass
- `typed_error_shape`: pass (`error.code`, `error.message`, `error.details[]`)

Interpretation:
- Sprint 1 contract surface remains intact after latency tuning rollout.

### 3) Staging env rollout audit

- Required Sprint 1 vars present:
  - rerank: `RERANK_*`, `MODEL_INFERENCE_RERANK_TIMEOUT_S`
  - search contract flags: `SEARCH_*`
  - fusion flags: `QUERY_FUSION_*` (optional `QUERY_FUSION_WEIGHTS` unset by design)

Interpretation:
- Terraform/runtime env rollout is complete for Sprint 1 staging query.

## Go/No-Go

- **Gate decision: GO for Sprint 2 transition**

Rationale:
1. Quality target met (`MRR@10` gain with stable recall/overlap)
2. Latency no longer regresses under rerank-on
3. Contract smoke and env audit pass
